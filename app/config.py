# app/config.py
import os
from pathlib import Path
from typing import Final

# ── Raíz del proyecto ───────────────────────────────────────
PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]  # …/pre_carga_cat

# ── .env opcional (solo entornos de desarrollo) ─────────────
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    from dotenv import load_dotenv  # type: ignore  (solo dev)
    load_dotenv(ENV_FILE, override=False)

def _env(key: str, *, required: bool = False, default: str | None = None) -> str:
    """Helper para leer variables de entorno con validación opcional."""
    val = os.getenv(key, default)
    if val is None and required:
        raise RuntimeError(f"Falta la variable de entorno obligatoria: {key}")
    return val


# ── Otros recursos ──────────────────────────────────────────
# — Autenticación Google —
GOOGLE_CLIENT_ID     = _env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _env("GOOGLE_CLIENT_SECRET")
FLASK_SECRET         = _env("FLASK_SECRET")

# Si no existen en variables de entorno => intentamos en credentials.json
if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
    import json
    cred_path = PROJECT_ROOT / _env("GOOGLE_CREDENTIALS_FILE", default="credentials.json")
    if cred_path.exists():
        with open(cred_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            GOOGLE_CLIENT_ID     = data.get("web", {}).get("client_id")     or GOOGLE_CLIENT_ID
            GOOGLE_CLIENT_SECRET = data.get("web", {}).get("client_secret") or GOOGLE_CLIENT_SECRET


HEADLESS: bool = _env("HEADLESS", default="True").lower() in {"1", "true", "yes"}
LOG_LEVEL: str = _env("LOG_LEVEL", default="INFO")

REPORTS_DIR: Path = (PROJECT_ROOT / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Exportables ─────────────────────────────────────────────
__all__ = [
    "REPORTS_DIR", "HEADLESS",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "FLASK_SECRET"
]