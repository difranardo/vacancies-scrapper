from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

from app.logging_utils import configure_logging


def create_app() -> Flask:
    """Create and configure a Flask application."""
    load_dotenv()
    app = Flask(__name__)
    CORS(app)
    configure_logging(app)

    from ..infrastructure.routes import bp as web_bp
    app.register_blueprint(web_bp)

    return app
