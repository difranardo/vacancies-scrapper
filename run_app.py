from __future__ import annotations
import io
import json
import threading
from pathlib import Path
from typing import Any, Callable
from flask import Flask, abort, current_app, jsonify, request, send_file, render_template
from flask_cors import CORS
import pandas as pd
from dotenv import load_dotenv

from app.logging_utils import configure_logging

# Módulos propios
from app.domain.scraper_control import ask_to_stop, get_result, new_job, set_result, stop_job
from app.infrastructure.bumeran import scrap_jobs_bumeran
from app.infrastructure.computrabajo import scrape_computrabajo
from app.infrastructure.zonajobs import scrape_zonajobs

load_dotenv()
app = Flask(__name__)
CORS(app)
configure_logging(app)

SCRAPERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "bumeran": scrap_jobs_bumeran,
    "zonajobs": scrape_zonajobs,
    "computrabajo": scrape_computrabajo,
}

@app.get("/")
def index():
    return render_template("index.html")

@app.route('/health')
def health():
    return "OK"

@app.post("/scrape")
def start_scrape():
    current_app.logger.debug("LLEGÓ UNA REQUEST A /scrape")
    data = request.get_json(force=True)
    current_app.logger.debug("Payload recibido: %s", data)
    portal = data.get("sitio")
    fmt    = data.get("formato", "json")
    func   = SCRAPERS.get(portal)
    if not func:
        abort(400, "Portal no válido")
    job_id = new_job()

    # Lanzar worker en background
    threading.Thread(
        target=_worker_scrape,
        args=(portal, data, job_id, func, set_result, app),
        daemon=True
    ).start()

    return jsonify(job_id=job_id, fmt=fmt, portal=portal)

def _worker_scrape(
    portal: str, data: dict, job_id: str, func: Callable, set_result: Callable, app: Flask
):
    with app.app_context():
        kwargs: dict[str, Any] = {"job_id": job_id}
        cargo = data.get("cargo", "").strip()
        ubic = data.get("ubicacion", "").strip()

        # Cargar parámetros base según el portal
        if portal == "computrabajo":
            kwargs["categoria"] = cargo
            kwargs["lugar"] = ubic
        elif portal in ("bumeran", "zonajobs", "mpar"):
            if cargo:
                kwargs["query"] = cargo
            if ubic:
                kwargs["location"] = ubic

        # Permitir límite de páginas si lo pasan desde el front
        max_pages = data.get("pages") or data.get("max_pages")
        if max_pages:
            try:
                kwargs["max_pages"] = int(max_pages)
            except Exception:
                current_app.logger.warning(
                    "Parametro de páginas inválido: %s", max_pages
                )

        current_app.logger.debug("Scraper %s – kwargs: %s", portal, kwargs)

        # Ejecución y manejo de errores
        try:
            res = func(**kwargs)
        except Exception as exc:
            current_app.logger.exception("Scraper %s falló: %s", portal, exc)
            res = []
        set_result(job_id, res)

@app.post("/stop-scrape")
def stop_scrape():
    payload = request.get_json(silent=True) or {}
    job_id = payload.get("job_id") or request.args.get("job_id")
    if not job_id:
        return {"ok": False, "error": "job_id requerido"}, 400
    stop_job(job_id)
    return {"ok": True}

@app.route("/download/<job_id>", methods=["HEAD", "GET"])
def download(job_id):
    data = get_result(job_id)

    # HEAD – ¿está listo el resultado?
    if request.method == "HEAD":
        if data is None:
            return ("", 404)
        if not data:
            return ("", 204)
        return ("", 200)

    # GET – enviar archivo
    if data is None:
        abort(404)
    if not data:
        return ("No data", 204)

    fmt = request.args.get("fmt", "json").lower()
    filename = f"{job_id}.{ 'xlsx' if fmt == 'excel' else 'json' }"
    return _excel_response(data, filename) if fmt == "excel" else _json_response(data, filename)

# Helpers de respuesta
def _json_response(payload: list[dict[str, Any]], filename: str):
    buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode())
    buf.seek(0)
    return send_file(buf, as_attachment=True, mimetype="application/json", download_name=filename)

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def _excel_response(payload: list[dict[str, Any]], filename: str):
    df = pd.DataFrame(payload or [])
    buf = io.BytesIO()
    for engine in ("xlsxwriter", "openpyxl"):
        try:
            with pd.ExcelWriter(buf, engine=engine) as writer:
                df.to_excel(writer, index=False, sheet_name="vacantes")
            break
        except ImportError as exc:
            current_app.logger.warning("Excel engine '%s' no disponible: %s", engine, exc)
            buf.seek(0)
            buf.truncate(0)
    else:
        raise RuntimeError(
            "Para generar Excel instalá:\n"
            "    pip install XlsxWriter   # o\n"
            "    pip install openpyxl"
        )

    buf.seek(0)
    return send_file(buf, as_attachment=True, mimetype=MIME_XLSX, download_name=filename)

if __name__ == "__main__":
    app.run(debug=True)
