# app/auth/application/login_google.py
from __future__ import annotations  

import secrets

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



def is_authenticated():
    if not current_user.is_authenticated:
            session["next_url"] = request.url
            return redirect(url_for("auth.login"))

# ─────── Blueprint "auth" ───────
auth_bp = Blueprint("auth", __name__)
# 1️⃣  PÁGINA DE LOGIN (renderiza HTML)
@auth_bp.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect('/')
    # Guarda a dónde volver después del login
    session["next_url"] = request.args.get("next") or request.referrer \
                          or url_for('auth.login')
    return render_template("login.html")

# 2️⃣  ENDPOINT que dispara OAuth
@auth_bp.route("/login/google")
def login_google():
    nonce = secrets.token_urlsafe(16)
    session["oauth_nonce"] = nonce
    redirect_uri = request.url_root.rstrip("/")         # host dinámico
    current_app.logger.debug("redirect_uri=%s", redirect_uri)
    return authorize_redirect(redirect_uri,nonce)

# 3️⃣  CALLBACK + LANDING protegida
@auth_bp.route("/")
def index_root():
    # --- Llegada desde Google ---
    if "code" in request.args:
        try:
            nonce  = session.pop("oauth_nonce", None)
            email, name = get_user_email(nonce)
            user = set_user(email,name)
            login_user(user)
            return redirect(session.pop("next_url", "/"))
        except Exception as err:                         # noqa: BLE001
            current_app.logger.exception("OAuth error: %s", err)
            return "Autenticación fallida", 500

    # --- Página protegida por cookie ---
    if not current_user.is_authenticated:
        session["next_url"] = request.url
        return redirect(url_for("auth.login"))
    return render_template("index.html", nombre=current_user.name)

# 4️⃣  LOGOUT
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

# ─────── init_app para integrarlo en tu factory ───────
def init_auth(app: Flask) -> None:
    lm = LoginManager(app)
    lm.user_loader(get_user)
    lm.login_view = "auth.login" # A dónde redirigir si el usuario no está logueado
    init_oauth(app)

    # --- INICIO DEL CÓDIGO PARA BYPASS ---
    # Si la configuración BYPASS_LOGIN es True, se ejecuta esta lógica
    if app.config.get("BYPASS_LOGIN"):
        @app.before_request
        def auto_login_for_testing():
            """Crea y loguea un usuario de prueba automáticamente."""
            # Revisa si ya hay un usuario logueado para no hacerlo en cada request
            if not current_user.is_authenticated:
                # Usamos tus propias funciones para crear/obtener el usuario
                test_user_email = "test.user@example.com"
                user = set_user(test_user_email, "Usuario de Prueba")
                login_user(user) # Inicia la sesión para este usuario
    # --- FIN DEL CÓDIGO PARA BYPASS ---