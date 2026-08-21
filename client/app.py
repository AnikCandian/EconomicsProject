"""Flask frontend for the deal-likelihood game.

This is a thin template/static-file server -- it holds no game state of its
own and makes no calls to the backend itself. Every page's JavaScript talks
directly to the FastAPI backend (economicsproject.server) over the REST API
described in ../API_PROTOCOL.md; Flask's only job is handing out the
HTML/CSS/JS that does that talking.

Pages are a reimplementation of the "Deal Probability" Claude Design mockup,
rebranded as "Quinn Labs" -- see README.md, "Design origin," for what
changed and why.

Run with:
    API_BASE_URL=http://127.0.0.1:8000 python app.py
"""

from __future__ import annotations

import os

from flask import Flask, render_template

app = Flask(__name__)

# Baked into every page as window.API_BASE_URL so browser JS knows where to
# send fetch() calls. Point this at wherever the FastAPI backend runs.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")

# Static landing-page copy, verified against the bundled dataset (not an
# API call -- this client is a separate deployable and doesn't import the
# backend package). Recompute these if the dataset ever changes:
#   from economicsproject.dataset import load_prepared_dataset, USABLE_COLUMNS, TARGET_COLUMN
#   ds = load_prepared_dataset(); train, _, _ = ds.split_by_season()
#   len(USABLE_COLUMNS), round(train[TARGET_COLUMN].mean() * 100, 1)
USABLE_COLUMN_COUNT = 32
TRAIN_BASE_RATE = 52.0


@app.context_processor
def inject_globals():
    return {
        "api_base_url": API_BASE_URL,
        "usable_column_count": USABLE_COLUMN_COUNT,
        "base_rate": TRAIN_BASE_RATE,
    }


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/play")
def play():
    return render_template("play.html")


@app.route("/professor")
def professor():
    return render_template("professor.html")


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=bool(os.environ.get("FLASK_DEBUG")),
        threaded=True,  # each page loads several static assets concurrently;
        # Werkzeug's dev server is single-threaded by default and can
        # otherwise truncate a response while serving others in parallel
    )
