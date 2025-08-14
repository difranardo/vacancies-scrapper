from flask import Flask
from app.auth.application.login_google import  auth_bp, init_auth, is_authenticated
from app.scraper.application.scraper_routes import scraper_bp

@scraper_bp.before_request
def must_be_logged():
    return is_authenticated()

def set_routes(app:Flask) -> None:

    @app.route("/health")
    def health_check():
        return "CAT OK"

    #Auth routes
    init_auth(app)
    app.register_blueprint(auth_bp)
    #Cat routes
    app.register_blueprint(scraper_bp)
