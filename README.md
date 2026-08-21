# EconomicsProject

Backend for a classroom "deal-likelihood" game: a professor hosts a session,
students pick predictor variables, and each gets a logit model scored live
against a Shark Tank deal-outcome dataset. Full API contract is in
[`API_PROTOCOL.md`](API_PROTOCOL.md).

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies. This also installs the project itself in editable
   mode (`requirements.txt` ends with `-e .`), so `economicsproject` is
   importable without a separate step:

   ```bash
   pip install -r requirements-dev.txt
   ```

   (Use `requirements.txt` instead if you don't need dev/test tools like `pytest`.)

## Usage

Run the API server:

```bash
PROFESSOR_API_KEY=<a real secret> python -m economicsproject.main
```

Serves on `http://127.0.0.1:8000` by default (override with `HOST`/`PORT`).
Interactive docs at `/docs`. See [`API_PROTOCOL.md`](API_PROTOCOL.md) for
every endpoint, request/response shape, and the auth model.

Run a one-off console demo of the modeling pipeline instead (no server):

```bash
python -m economicsproject.main --demo
```

## Testing

```bash
pytest
```

## Deploying

See [`DEPLOY.md`](DEPLOY.md) for running this backend and
[`client/`](client/) as two Cloud Run services on Google Cloud, built
straight from source with Google's buildpacks (no Dockerfile needed).

## Project structure

```
.
├── API_PROTOCOL.md               # REST API contract for the game backend
├── DEPLOY.md                     # Cloud Run / buildpack deployment steps
├── Procfile                      # buildpack entry point for this backend service
├── src/
│   └── economicsproject/
│       ├── Shark Tank US dataset.csv        # raw data, never modified
│       ├── prepared_shark_tank_dataset.csv  # derived, gitignored, regenerated on startup
│       ├── dataset.py    # USABLE_COLUMNS, category encoding, PreparedDataset
│       ├── modeling.py   # fit_logit_model, scoring
│       ├── cache.py      # ModelCache: fit each variable set at most once
│       ├── sessions.py   # game session state (students, submissions, leaderboards)
│       ├── schemas.py    # request body validation
│       ├── server.py     # FastAPI app / REST routes
│       └── main.py       # CLI entry point (server, or --demo)
├── tests/                # one test file per module above
├── requirements.txt      # runtime dependencies
├── requirements-dev.txt  # + pytest, httpx (for API tests)
└── pyproject.toml        # package metadata
```
