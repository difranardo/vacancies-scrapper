from __future__ import annotations

import io
import json
from typing import Any, Callable

import pandas as pd
from flask import Flask, current_app, send_file


MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _worker_scrape(
    portal: str,
    data: dict,
    job_id: str,
    func: Callable,
    set_result: Callable,
    app: Flask,
):
    with app.app_context():
        kwargs: dict[str, Any] = {"job_id": job_id}
        cargo = data.get("cargo", "").strip()
        ubic = data.get("ubicacion", "").strip()

        if portal == "computrabajo":
            kwargs["categoria"] = cargo
            kwargs["lugar"] = ubic
        elif portal in ("bumeran", "zonajobs", "mpar"):
            if cargo:
                kwargs["query"] = cargo
            if ubic:
                kwargs["location"] = ubic

        max_pages = data.get("pages") or data.get("max_pages")
        if max_pages:
            try:
                kwargs["max_pages"] = int(max_pages)
            except Exception:
                current_app.logger.warning(
                    "Parametro de páginas inválido: %s", max_pages
                )


    headless = data.get("headless")
    if headless is not None:
        if isinstance(headless, str):
            kwargs["headless"] = headless.lower() in ("1", "true", "yes", "y")
        else:
            kwargs["headless"] = bool(headless)

    app.logger.debug("Scraper %s – kwargs: %s", portal, kwargs)



        try:
            res = func(**kwargs)
        except Exception as exc:
            current_app.logger.exception("Scraper %s falló: %s", portal, exc)
            res = []
        set_result(job_id, res)


def _json_response(payload: list[dict[str, Any]], filename: str):
    buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode())
    buf.seek(0)
    return send_file(
        buf, as_attachment=True, mimetype="application/json", download_name=filename
    )


def _excel_response(payload: list[dict[str, Any]], filename: str):
    df = pd.DataFrame(payload or [])
    buf = io.BytesIO()
    for engine in ("xlsxwriter", "openpyxl"):
        try:
            with pd.ExcelWriter(buf, engine=engine) as writer:
                df.to_excel(writer, index=False, sheet_name="vacantes")
            break
        except ImportError as exc:
            current_app.logger.warning(
                "Excel engine '%s' no disponible: %s", engine, exc
            )
            buf.seek(0)
            buf.truncate(0)
    else:
        raise RuntimeError(
            "Para generar Excel instalá:\n"
            "    pip install XlsxWriter   # o\n"
            "    pip install openpyxl"
        )

    buf.seek(0)
    return send_file(
        buf, as_attachment=True, mimetype=MIME_XLSX, download_name=filename
    )
