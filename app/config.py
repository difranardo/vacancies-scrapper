# app/config.py
import os
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]

ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE, override=False)

def _env(key: str, *, required: bool = False, default: str | None = None) -> str:
    val = os.getenv(key, default)
    if val is None and required:
        raise RuntimeError(f"Falta la variable de entorno obligatoria: {key}")
    return val

# Autenticación Google
GOOGLE_CLIENT_ID     = _env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _env("GOOGLE_CLIENT_SECRET")
FLASK_SECRET         = _env("FLASK_SECRET", default="dev_secret_key_change_me")

# Nuevo: flag para bypass
BYPASS_LOGIN: bool = _env("BYPASS_LOGIN", default="false").lower() in {"1", "true", "yes"}

HEADLESS: bool = _env("HEADLESS", default="True").lower() in {"1", "true", "yes"}
LOG_LEVEL: str = _env("LOG_LEVEL", default="INFO")

REPORTS_DIR: Path = (PROJECT_ROOT / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

__all__ = [
    "REPORTS_DIR", "HEADLESS",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "FLASK_SECRET",
    "BYPASS_LOGIN",
]
