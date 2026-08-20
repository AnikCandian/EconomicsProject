"""Barebones Flask frontend for the deal-likelihood game.

This is a thin template/static-file server -- it holds no game state of its
own and makes no calls to the backend itself. Every page's JavaScript talks
directly to the FastAPI backend (economicsproject.server) over the REST API
described in ../API_PROTOCOL.md; Flask's only job is handing out the
HTML/CSS/JS that does that talking.

This is the original minimal-styling client, kept alongside ../client/ (the
Deal Probability-designed one) as a plainer alternative -- useful for
quickly eyeballing raw API responses without the styled UI in the way, or
if you'd rather build your own design on top of a simple starting point.
See ../client/README.md, "Design origin," for what the other one adds.

Run with:
    API_BASE_URL=http://127.0.0.1:8000 python app.py

Defaults to port 5001 (../client/ defaults to 5000) so both can run side by
side on one machine without a port clash.
"""

from __future__ import annotations

import os

from flask import Flask, render_template

app = Flask(__name__)

# Baked into every page as window.API_BASE_URL so browser JS knows where to
# send fetch() calls. Point this at wherever the FastAPI backend runs.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")


@app.context_processor
def inject_api_base_url():
    return {"api_base_url": API_BASE_URL}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/professor")
def professor():
    return render_template("professor.html")


@app.route("/join")
def join():
    return render_template("student_join.html")


@app.route("/play")
def play():
    return render_template("student_game.html")


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5001")),
        debug=bool(os.environ.get("FLASK_DEBUG")),
        threaded=True,  # avoid the dev server serializing concurrent asset requests
    )
