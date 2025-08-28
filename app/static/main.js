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
var astK = document.getElementById("asterisk-keyword");
var astL = document.getElementById("asterisk-location");


/* ============================= Estado ============================ */
var currentJobId = null;      // último job activo
var activeCtrl   = null;      // AbortController del POST /api/scrape
var pollTimerId  = 0;         // setTimeout id para polling
var pollingJobId = null;      // job al que apunta el polling actual
var pollCtrl     = null;
var isJobStopping = false;      

/* =========================== Utilidades ========================== */
function show(el){ if (el) el.style.display = "block"; }
function hide(el){ if (el) el.style.display = "none"; }

function showToast(message) {
  var toast = document.createElement("div");
  toast.textContent = message;
  toast.style.position = "fixed";
  toast.style.bottom = "20px";
  toast.style.left = "50%";
  toast.style.transform = "translateX(-50%)";
  toast.style.backgroundColor = "#333";
  toast.style.color = "white";
  toast.style.padding = "10px 20px";
  toast.style.borderRadius = "5px";
  toast.style.zIndex = "1000";
  toast.style.opacity = "0";
  toast.style.transition = "opacity 0.5s";
  
  document.body.appendChild(toast);

  // Animar la aparición
  setTimeout(function() {
    toast.style.opacity = "1";
  }, 10);

  // Ocultar y eliminar después de 4 segundos
  setTimeout(function() {
    toast.style.opacity = "0";
    setTimeout(function() {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 500); // Esperar a que la transición de opacidad termine
  }, 4000);
}

function updateRequiredByPortal() {
  var isCT = portalSel && portalSel.value === "computrabajo";
  if (keywordInp)  keywordInp.required  = isCT;
  if (locationInp) locationInp.required = isCT;
  if (astK) astK.toggleAttribute("hidden", !isCT);
  if (astL) astL.toggleAttribute("hidden", !isCT);
}

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
        if (isJobStopping) return;
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
        if (isJobStopping) return;
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

  updateRequiredByPortal();
  if (portalSel) portalSel.addEventListener("change", updateRequiredByPortal);

  if (form){
    form.addEventListener("submit", function(e){
      e.preventDefault();

      updateRequiredByPortal();

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

if (cancelBtn) {
  cancelBtn.addEventListener("click", async function () {
    if (!currentJobId) {
      resetAfterJob();
      return;
    }

    clearPolling();
    cancelBtn.disabled = true;
    const jobId = currentJobId;

    try {
      await fetch("/stop-scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId })
      });

      // 1. La UI se restablece en la memoria
      resetAfterJob();
      showToast("Proceso detenido. Preparando descarga...");

      // 2. Comprobamos la descarga en segundo plano
      fetch("/api/download/" + jobId + "?fmt=excel&keep=1", { method: "HEAD", cache: "no-store" })
        .then(head => {
          if (head.status === 200) {
            // 3. ¡LA CLAVE ESTÁ AQUÍ!
            // Le damos al navegador la oportunidad de actualizar la pantalla ANTES de descargar.
            setTimeout(function() {
              console.log("La UI ya debería estar visiblemente actualizada. Iniciando descarga.");
              const a = document.createElement("a");
              a.href = "/api/download/" + jobId + "?fmt=excel&keep=1";
              a.download = jobId + "_parcial.xlsx";
              document.body.appendChild(a);
              a.click();
              a.remove();
            }, 0); // El '0' pone esta tarea al final de la cola, permitiendo el repintado.
          }
        })
        .catch(err => {
          console.error("Error al comprobar el archivo parcial:", err);
        });

    } catch (err) {
      console.error("Error de red al detener el proceso:", err);
      showToast("Error de red al intentar detener el proceso.");
      resetAfterJob();
    }
  });
}