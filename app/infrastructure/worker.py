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
    """
    Ejecuta un scraper en un hilo secundario dentro del contexto de la aplicación Flask.
    """
    # Inicia el contexto de la aplicación para todo el proceso del worker.
    with app.app_context():
        kwargs: dict[str, Any] = {"job_id": job_id}
        cargo = data.get("cargo", "").strip()
        ubic = data.get("ubicacion", "").strip()

        # Mejora: Usar un diccionario de mapeo para los parámetros del portal.
        # Es más limpio y fácil de extender que un if/elif.
        portal_params_map = {
            "computrabajo": {"categoria": cargo, "lugar": ubic},
            "bumeran": {"query": cargo, "location": ubic},
            "zonajobs": {"query": cargo, "location": ubic},
            "mpar": {"query": cargo, "location": ubic},
        }
        
        # Filtra claves con valores vacíos antes de actualizar kwargs.
        params = {k: v for k, v in portal_params_map.get(portal, {}).items() if v}
        kwargs.update(params)

        # Manejo del número de páginas.
        max_pages = data.get("pages") or data.get("max_pages")
        if max_pages:
            try:
                kwargs["max_pages"] = int(max_pages)
            # Mejora: Captura excepciones más específicas.
            except (ValueError, TypeError):
                current_app.logger.warning(
                    "Parámetro de páginas inválido: '%s'. Se ignorará.", max_pages
                )
        
        # Manejo del parámetro headless.
        headless = data.get("headless")
        if headless is not None:
            if isinstance(headless, str):
                kwargs["headless"] = headless.lower() in ("1", "true", "yes", "y")
            else:
                kwargs["headless"] = bool(headless)

        current_app.logger.debug("Iniciando scraper %s con parámetros: %s", portal, kwargs)

        res = []
        try:
            # La función del scraper se ejecuta.
            res = func(**kwargs)
        except Exception as exc:
            # Si el scraper falla, se registra la excepción completa.
            current_app.logger.exception("Scraper '%s' falló inesperadamente.", portal)
        
        # ¡Corrección principal! Llamar a set_result DENTRO del contexto.
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
