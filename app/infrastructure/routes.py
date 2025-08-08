from __future__ import annotations

import threading
from typing import Any, Callable

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
)


from app.domain.scraper_control import (
    get_result,
    new_job,
    remove_job,
    set_result,
    stop_job,
)
from app.infrastructure.bumeran.scraper import scrape_bumeran

from app.infrastructure.computrabajo import scrape_computrabajo
from app.infrastructure.zonajobs import scrape_zonajobs

from .worker import _excel_response, _json_response, _worker_scrape

bp = Blueprint("web", __name__)

SCRAPERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "bumeran": scrap_jobs_bumeran,
    "zonajobs": scrape_zonajobs,
    "computrabajo": scrape_computrabajo,
}


@bp.get("/")
def index():
    return render_template("index.html")


@bp.route("/health")
def health():
    return "OK"


@bp.post("/scrape")
def start_scrape():
    current_app.logger.debug("LLEGÓ UNA REQUEST A /scrape")
    data = request.get_json(force=True)
    current_app.logger.debug("Payload recibido: %s", data)
    portal = data.get("sitio")
    fmt = data.get("formato", "json")
    func = SCRAPERS.get(portal)
    if not func:
        abort(400, "Portal no válido")

    job_id = new_job()

    threading.Thread(
        target=_worker_scrape,
        args=(portal, data, job_id, func, set_result, current_app._get_current_object()),
        daemon=True,
    ).start()

    return jsonify(job_id=job_id, fmt=fmt, portal=portal)


@bp.post("/stop-scrape")
def stop_scrape():
    payload = request.get_json(silent=True) or {}
    job_id = payload.get("job_id") or request.args.get("job_id")
    if not job_id:
        return {"ok": False, "error": "job_id requerido"}, 400
    stop_job(job_id)
    return {"ok": True}


@bp.route("/download/<job_id>", methods=["HEAD", "GET"])
def download(job_id):
    data = get_result(job_id)

    if request.method == "HEAD":
        if data is None:
            return ("", 404)
        if not data:
            return ("", 204)
        return ("", 200)

    if data is None:
        abort(404)
    if not data:
        remove_job(job_id)
        return ("No data", 204)

    fmt = request.args.get("fmt", "json").lower()
    filename = f"{job_id}.{'xlsx' if fmt == 'excel' else 'json'}"
    resp = (
        _excel_response(data, filename)
        if fmt == "excel"
        else _json_response(data, filename)
    )
    remove_job(job_id)
    return resp
