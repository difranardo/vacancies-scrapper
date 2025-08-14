# app/routes.py
from flask import Flask, render_template
from app.scraper.application.scraper_routes import scraper_bp

def set_routes(app: Flask) -> None:
    @app.route("/health")
    def health_check():
        return "CAT OK", 200

    @app.route("/")
    def home():
        # Renderiza tu formulario
        return render_template("index.html")

    # Registrar blueprint del scraper
    app.register_blueprint(scraper_bp)

    # (Opcional) favicon para evitar logs molestos
    @app.route("/favicon.ico")
    def _favicon():
        from flask import send_from_directory, current_app
        return send_from_directory(current_app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")
