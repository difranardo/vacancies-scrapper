# app/auth/application/login_google.py
from __future__ import annotations
import secrets
import os

from flask import (
    Blueprint, Flask, current_app, redirect,
    render_template, request, session, url_for,
)
from flask_login import (
    LoginManager, current_user,
    login_user, logout_user, login_required,
)

from app.auth.infrastructure.oauth import authorize_redirect, get_user_email, init_oauth
from app.auth.infrastructure.user import get_user, set_user


# ─────── Blueprint "auth" ───────
auth_bp = Blueprint("auth", __name__)

# 1️⃣ Página de login (renderiza HTML si no hay bypass)
@auth_bp.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect("/")
    session["next_url"] = request.args.get("next") or request.referrer or url_for("auth.login")
    return render_template("login.html")

# 2️⃣ Inicia OAuth (solo se usará cuando BYPASS esté apagado)
@auth_bp.route("/login/google")
def login_google():
    nonce = secrets.token_urlsafe(16)
    session["oauth_nonce"] = nonce
    redirect_uri = request.url_root.rstrip("/")
    current_app.logger.debug("redirect_uri=%s", redirect_uri)
    return authorize_redirect(redirect_uri, nonce)

# 3️⃣ Callback y home protegida
@auth_bp.route("/")
def index_root():
    # Si viene de Google OAuth
    if "code" in request.args:
        try:
            nonce = session.pop("oauth_nonce", None)
            email, name = get_user_email(nonce)
            user = set_user(email, name)
            login_user(user)
            return redirect(session.pop("next_url", "/"))
        except Exception as err:                         # noqa: BLE001
            current_app.logger.exception("OAuth error: %s", err)
            return "Autenticación fallida", 500

    # Cookie de sesión
    if not current_user.is_authenticated:
        session["next_url"] = request.url
        return redirect(url_for("auth.login"))
    return render_template("index.html", nombre=current_user.name)

# 4️⃣ Logout
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

# ─────── Inicialización de auth (application factory) ───────
def init_auth(app: Flask) -> None:
    lm = LoginManager(app)
    lm.user_loader(get_user)
    lm.login_view = "auth.login"
    init_oauth(app)

    # 🔧 BYPASS opcional para testing (auto-login)
    if app.config.get("BYPASS_LOGIN"):
        @app.before_request
        def auto_login_for_testing():
            if not current_user.is_authenticated:
                test_user_email = "test.user@example.com"
                user = set_user(test_user_email, "Usuario de Prueba")
                login_user(user)
