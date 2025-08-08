from __future__ import annotations

from datetime import datetime, timedelta
import re


def parse_fecha_publicacion(texto: str) -> str:
    """Convierte fechas relativas en texto a fecha absoluta dd/mm/yyyy"""
    if not texto:
        return ""
    hoy = datetime.now()

    # Hace X días/horas/minutos
    match = re.search(r"hace (\d+) (minuto|minutos|hora|horas|día|días)", texto, re.IGNORECASE)
    if match:
        valor, unidad = int(match.group(1)), match.group(2)
        if "minuto" in unidad:
            fecha = hoy - timedelta(minutes=valor)
        elif "hora" in unidad:
            fecha = hoy - timedelta(hours=valor)
        elif "día" in unidad:
            fecha = hoy - timedelta(days=valor)
        else:
            fecha = hoy
        return fecha.strftime("%d/%m/%Y")

    # Hace más de X días
    match = re.search(r"hace más de (\d+) días", texto, re.IGNORECASE)
    if match:
        valor = int(match.group(1))
        fecha = hoy - timedelta(days=valor)
        return fecha.strftime("%d/%m/%Y")

    # Ayer
    if "ayer" in texto.lower():
        fecha = hoy - timedelta(days=1)
        return fecha.strftime("%d/%m/%Y")

    # Solo "actualizada" (sin otra info) → dejar vacío, o podés poner la fecha de hoy
    if "actualizada" in texto.lower():
        return ""  # o return hoy.strftime("%d/%m/%Y") si preferís

    return hoy.strftime("%d/%m/%Y")  # fallback por si hay algo nuevo

