/* static/main.js */
const form       = document.getElementById("scrapeForm");
const portalSel  = document.getElementById("portal");
const keywordInp = document.getElementById("keyword");
const locationInp= document.getElementById("location");
const pagesInp   = document.getElementById("pages");
const loadingDiv = document.getElementById("loading");
const cancelBtn  = document.getElementById("btnCancel");
const table      = document.getElementById("resultsTable");
const tbody      = table.querySelector("tbody");

let currentJob = null;
const POLL_MS = 3500;

/* ─────────────────── UX helpers ─────────────────── */
function show(el){ el.style.display = "flex"; }
function hide(el){ el.style.display = "none"; }
function enable(el, ok=true){ el.disabled = !ok; }
function resetFormUI(){
  hide(loadingDiv); enable(form, true); currentJob=null;
  document.getElementById("downloadWrap").style.display = "none";
}

/* ─── Reglas de campos obligatorios ──────────────── */
function updateRequired(){
  const isCT = portalSel.value === "computrabajo";
  keywordInp.required  = isCT;
  locationInp.required = isCT;
}
portalSel.addEventListener("change", updateRequired);
updateRequired();

/* ─── Iniciar scraping ───────────────────────────── */
form.addEventListener("submit", async e=>{
  e.preventDefault();

  const payload = {
    sitio:   portalSel.value,
    formato: "json",
    cargo:   keywordInp.value.trim(),
    ubicacion: locationInp.value.trim(),
    pages:  parseInt(pagesInp.value,10)||1
  };

  enable(form,false); show(loadingDiv);

  const res = await fetch("/scrape",{
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify(payload)
  });
  if(!res.ok){ alert(await res.text()); resetFormUI(); return; }

  const { job_id } = await res.json();
  currentJob = job_id;
  pollStatus();
});

/* ─── Polling de estado ──────────────────────────── */
async function pollStatus(){
  if(!currentJob) return;
  const head = await fetch(`/download/${currentJob}`,{ method:"HEAD" });

  switch(head.status){
    case 404:                     // todavía procesando
      setTimeout(pollStatus, POLL_MS);
      break;
    case 204:                     // terminó sin datos
      alert("No se encontraron resultados.");
      resetFormUI();
      break;
    case 200:                     // listo ✔
      fetchResults();
      break;
    default:
      alert(`Error inesperado (${head.status})`);
      resetFormUI();
  }
}

/* ─── Descargar y pintar tabla ───────────────────── */
async function fetchResults(){
  const res = await fetch(`/download/${currentJob}?fmt=json`);
  const rows = await res.json();
  renderTable(rows);
  document.getElementById("btnExcel").href = `/download/${currentJob}?fmt=excel`;
  document.getElementById("downloadWrap").style.display = "block";
  resetFormUI();
}
function renderTable(rows){
  tbody.innerHTML = "";
  rows.forEach(r=>{
    tbody.insertAdjacentHTML("beforeend",`
      <tr>
        <td>${r.titulo||""}</td>
        <td>${r.empresa||""}</td>
        <td>${r.ubicacion||""}</td>
        <td><a href="${r.url}" target="_blank">Ver</a></td>
      </tr>
    `);
  });
  table.style.display = rows.length? "table":"none";
}

/* ─── Cancelación ────────────────────────────────── */
cancelBtn.addEventListener("click", async ()=>{
  if(!currentJob){ resetFormUI(); return; }
  await fetch("/stop-scrape",{ method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({ job_id: currentJob })
  });
  resetFormUI();
});
