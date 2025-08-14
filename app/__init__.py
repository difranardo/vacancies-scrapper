from __future__ import annotations
from datetime import timedelta
import logging
import os
from flask import Flask
from flask_cors import CORS
from app.config import LOG_LEVEL, FLASK_SECRET, BYPASS_LOGIN
from app.routes import set_routes
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Logger
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")

    # Config básica
    app.config["SECRET_KEY"] = FLASK_SECRET
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["APPLICATION_ROOT"] = "/"
    app.config["PREFERRED_URL_SCHEME"] = "https"
    app.config["BYPASS_LOGIN"] = BYPASS_LOGIN

    app.permanent_session_lifetime = timedelta(hours=4)

    # CORS
    CORS(app, supports_credentials=True)

    # Rutas
    set_routes(app)

    return app
