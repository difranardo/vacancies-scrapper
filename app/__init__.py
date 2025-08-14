from __future__ import annotations
from datetime import timedelta
import logging
import os  # Make sure 'os' is imported
from flask import Flask
from flask_cors import CORS
from app.config import LOG_LEVEL 
from app.routes import set_routes
from werkzeug.middleware.proxy_fix import ProxyFix


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    # ── Logger ───────────────────────────────────────────
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")

    # ── Básico ───────────────────────────────────────────
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config['APPLICATION_ROOT'] = '/'
    app.config['PREFERRED_URL_SCHEME'] = 'https'
    app.config["BYPASS_LOGIN"] = True

    app.permanent_session_lifetime = timedelta(hours=4)

    # ── CORS ─────────────────────────────────────────────
    CORS(app, supports_credentials=True)

    #--- ROUTER -----------
    set_routes(app)

    return app