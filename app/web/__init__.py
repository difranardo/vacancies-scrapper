from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv


def create_app() -> Flask:
    """Create and configure a Flask application."""
    load_dotenv()
    app = Flask(__name__)
    CORS(app)

    from .routes import bp as web_bp
    app.register_blueprint(web_bp)

    return app
