from __future__ import annotations

import threading, time
from typing import Any, Callable
from flask import Blueprint, abort, current_app, jsonify, request, send_file

from app.scraper.application.scraper_control import (
    get_result, new_job, remove_job, set_result, stop_job,
)
from app.infrastructure.providers.bumeran import scrap_jobs_bumeran
from app.infrastructure.providers.computrabajo import scrape_computrabajo
from app.infrastructure.providers.zonajobs import scrape_zonajobs
from app.infrastructure.worker import _excel_response, _json_response, _worker_scrape

scraper_bp = Blueprint("scraper", __name__)


# Registro de scrapers disponibles
SCRAPERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "bumeran":       scrap_jobs_bumeran,
    "zonajobs":      scrape_zonajobs,
    "computrabajo":  scrape_computrabajo,
}

@scraper_bp.post("/scrape")
def start_scrape():
    data = request.get_json(force=True) or {}
    portal = (data.get("sitio") or "").lower()
    func = SCRAPERS.get(portal)
    if not func:
        abort(400, "Portal no válido")

    job_id = new_job()

    # Ejecuta el scraper en background
    threading.Thread(
        target=_worker_scrape,
        args=(portal, data, job_id, func, set_result, current_app._get_current_object()),
        daemon=True,
    ).start()

    return jsonify(job_id=job_id, portal=portal)

@scraper_bp.post("/stop-scrape")
def stop_scrape_alias():
    """
    Marca stop y devuelve un Excel parcial si hay filas.
    Front: POST /stop-scrape  body: {"job_id": "..."}
    """
    data = request.get_json(force=True) or {}
    job_id = (data.get("job_id") or "").strip()
    if not job_id:
        abort(400, "job_id requerido")

    # 1) marcar cancelación (cooperativa)
    stop_job(job_id)

    # 2) esperar brevemente a que el worker “empuje” la fila en curso (hasta ~2.5s)
    t0 = time.time()
    rows = get_result(job_id) or []
    while not rows and (time.time() - t0) < 4.5:
        time.sleep(0.15)
        rows = get_result(job_id) or []

    # 3) si no hay nada, 204
    if not rows:
        return ("", 204)

    # 4) devolver Excel usando el helper existente
    return _excel_response(rows, f"{job_id}_parcial.xlsx")

@scraper_bp.route("/download/<job_id>", methods=["HEAD", "GET"])
def download(job_id: str):
    data = get_result(job_id)

    # HEAD → estado del resultado
    if request.method == "HEAD":
        if data is None:  # job inexistente / aún no registrado
            return ("", 404)
        if not data:      # existe pero sin filas (en progreso o terminó sin datos)
            return ("", 204)
        return ("", 200)  # hay datos (parcial o final)

    # GET → servir archivo
    if data is None:
        abort(404)
    if not data:
        return ("", 204)

    fmt = (request.args.get("fmt") or "json").lower()
    filename = f"{job_id}.{'xlsx' if fmt == 'excel' else 'json'}"
    resp = _excel_response(data, filename) if fmt == "excel" else _json_response(data, filename)

    # Limpieza opcional: keep=1 (default) conserva el job; keep=0 lo borra
    if request.args.get("keep", "1") == "0":
        remove_job(job_id)

    return resp