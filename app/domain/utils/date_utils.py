from datetime import datetime, timedelta
import re

def parse_fecha_publicacion(texto: str):
    """
    Convierte una fecha en texto del estilo 'Publicado hace 3 días'
    o 'Publicado el 10/05/2023' en un objeto datetime.date.
    """
    if not texto:
        return None

    texto = texto.lower().strip()

    # Caso: "hace X días"
    match = re.search(r"hace\s+(\d+)\s*d", texto)
    if match:
        dias = int(match.group(1))
        return (datetime.now() - timedelta(days=dias)).date()

    # Caso: fecha absoluta dd/mm/yyyy
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    if match:
        dia, mes, anio = map(int, match.groups())
        return datetime(anio, mes, dia).date()

    return None