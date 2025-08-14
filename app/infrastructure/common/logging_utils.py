import logging
import sys
from flask import Flask, current_app


def get_logger(name: str | None = None) -> logging.Logger:
    """Return current_app logger if available, otherwise a standard logger."""
    try:
        return current_app.logger
    except RuntimeError:
        return logging.getLogger(name or "vacancies-scrapper")


def configure_logging(app: Flask) -> None:
    """Configure application logging to standard output."""
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    if not app.logger.handlers:
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
