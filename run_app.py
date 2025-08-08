from flask import Flask, abort, current_app, jsonify, request, send_file, render_template
from app.web import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
