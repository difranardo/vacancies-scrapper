"use strict";

/* ============================== DOM ============================== */
var form         = document.getElementById("scrapeForm");
var portalSel    = document.getElementById("portal");
var keywordInp   = document.getElementById("keyword");
var locationInp  = document.getElementById("location");
var pagesInp     = document.getElementById("pages");
var loadingDiv   = document.getElementById("loading");
var cancelBtn    = document.getElementById("btnCancel");
var downloadWrap = document.getElementById("downloadWrap");
var btnExcel     = document.getElementById("btnExcel");

/* ============================= Estado ============================ */
var currentJobId = null;      // último job activo
var activeCtrl   = null;      // AbortController del POST /api/scrape
var pollTimerId  = 0;         // setTimeout id para polling
var pollingJobId = null;      // job al que apunta el polling actual
var pollCtrl     = null;      // AbortController del polling

/* =========================== Utilidades ========================== */
function show(el){ if (el) el.style.display = "block"; }
function hide(el){ if (el) el.style.display = "none"; }

function setUIRunning(running){
  // mostrar/ocultar “cargando” (overlay no bloquea clics)
  if (loadingDiv) {
    loadingDiv.style.display = running ? "block" : "none";
    loadingDiv.style.pointerEvents = "none"; // evita que bloquee el form
  }

  if (form){
    var submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (submitBtn) submitBtn.disabled = running;
  }

  if (cancelBtn) cancelBtn.disabled = !running;
}

function triggerExcelDownload(jobId){
  var url = "/api/download/" + jobId + "?fmt=excel&keep=1";
  if (btnExcel){
    btnExcel.href = url;
    show(downloadWrap);
  }
  var a = document.createElement("a");
  a.href = url;
  a.download = jobId + ".xlsx";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function clearPolling(){
  if (pollTimerId){ clearTimeout(pollTimerId); pollTimerId = 0; }
  if (pollCtrl){ pollCtrl.abort(); pollCtrl = null; }
  pollingJobId = null;
}

function resetAfterJob(){
  clearPolling();
  setUIRunning(false);
  currentJobId = null;
  if (cancelBtn) cancelBtn.removeAttribute("data-job-id");
}

/* ========================== Polling (HEAD) ======================= */
function startPolling(jobId){
  clearPolling();
  pollingJobId = jobId;
  pollCtrl = new AbortController();

  var delay = 2500;        // ms
  var maxDelay = 15000;

  function ping(){
    if (!pollCtrl || pollCtrl.signal.aborted || pollingJobId !== jobId) return;

    fetch("/api/download/" + jobId + "?fmt=excel", { method: "HEAD", cache: "no-store", signal: pollCtrl.signal })
      .then(function(res){
        if (!pollCtrl || pollCtrl.signal.aborted || pollingJobId !== jobId) return;
        if (res.status === 200){
          triggerExcelDownload(jobId);
          resetAfterJob();
          return;
        }
        if (res.status === 204){
          resetAfterJob();
          return;
        }
        pollTimerId = setTimeout(ping, delay);
        delay = Math.min(Math.floor(delay * 17 / 10), maxDelay);
      })
      .catch(function(){
        if (!pollCtrl || pollCtrl.signal.aborted || pollingJobId !== jobId) return;
        pollTimerId = setTimeout(ping, delay);
        delay = Math.min(Math.floor(delay * 17 / 10), maxDelay);
      });
  }

  ping();
}

/* ========================= Submit: start ========================= */
document.addEventListener("DOMContentLoaded", function(){
  var form        = document.getElementById("scrapeForm");
  var keywordInp  = document.getElementById("keyword");
  var locationInp = document.getElementById("location");

  if (form){
    form.addEventListener("submit", function(e){
      e.preventDefault();

      // Marcar campos como obligatorios
      if (keywordInp)  keywordInp.required  = true;
      if (locationInp) locationInp.required = true;

      // Si algún campo falla la validación nativa, cortar
      if (!form.reportValidity()) return;

      var pagesVal = 1;
      if (pagesInp && pagesInp.value){
        var p = parseInt(pagesInp.value, 10);
        if (!isNaN(p)) pagesVal = Math.max(1, Math.min(p, 50));
      }

      var payload = {
        sitio:     portalSel ? portalSel.value : "",
        formato:   "excel",
        cargo:     keywordInp ? (keywordInp.value || "").trim() : "",
        ubicacion: locationInp ? (locationInp.value || "").trim() : "",
        pages:     pagesVal
      };

      setUIRunning(true);

      if (activeCtrl && typeof activeCtrl.abort === "function") activeCtrl.abort();
      activeCtrl = (typeof AbortController !== "undefined") ? new AbortController() : null;

      var fetchOpts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      };
      if (activeCtrl) fetchOpts.signal = activeCtrl.signal;

      fetch("/api/scrape", fetchOpts)
        .then(function(res){
          if (!res.ok) return res.text().then(function(t){ throw new Error(t || ("HTTP " + res.status)); });
          return res.json();
        })
        .then(function(data){
          var jobId = data && data.job_id;
          if (!jobId) throw new Error("El backend no devolvió job_id.");
          currentJobId = jobId;
          if (cancelBtn) cancelBtn.setAttribute("data-job-id", jobId);
          startPolling(jobId);
        })
        .catch(function(err){
          console.error("No se pudo iniciar el scraping:", err);
          resetAfterJob();
        });
    });
  }
});

// Cancelar: detiene, intenta bajar parcial y NO deja la UI frizada
if (cancelBtn) {
  cancelBtn.addEventListener("click", async function () {
    if (!currentJobId) { resetAfterJob(); return; }

    // cortar polling y bloquear el botón
    clearPolling();
    cancelBtn.disabled = true;

    const jobId = currentJobId;

    try {
      const res = await fetch("/stop-scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId })
      });

      const ct = (res.headers.get("content-type") || "").toLowerCase();

      // A) backend devolvió el Excel directo
      if (res.ok && ct.includes("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = jobId + "_parcial.xlsx";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      }
      // B) 204: sin filas -> por si dejó el archivo en /download unos instantes
      else if (res.status === 204) {
        const head = await fetch("/download/" + jobId + "?fmt=excel&keep=1", { method: "HEAD", cache: "no-store" });
        if (head.status === 200) {
          const a = document.createElement("a");
          a.href = "/download/" + jobId + "?fmt=excel&keep=1";
          a.download = jobId + ".xlsx";
          document.body.appendChild(a);
          a.click();
          a.remove();
        } else {
          alert("No hay resultados parciales para descargar.");
        }
      } else {
        alert("No se pudo cancelar (HTTP " + res.status + ").");
      }
    } catch (err) {
      console.error(err);
      alert("Error de red al cancelar.");
    } finally {
      // 🔑 clave para NO dejar la web frizada
      resetAfterJob();
    }
  });
}