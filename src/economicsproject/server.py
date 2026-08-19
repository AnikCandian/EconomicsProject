"""RESTful API for the deal-likelihood classroom game.

This module is intentionally a thin HTTP layer: all game logic lives in
``sessions.py`` / ``cache.py`` / ``modeling.py`` / ``dataset.py``. See
API_PROTOCOL.md at the repo root for the full endpoint-by-endpoint contract.

Run it with:
    uvicorn economicsproject.server:app --reload
or:
    python -m economicsproject.main
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import schemas
from .cache import ModelCache
from .dataset import (
    CATEGORY_VALUES,
    DUMMY_COLUMN_CATEGORY,
    USABLE_COLUMNS,
    load_prepared_dataset,
    validate_variable_selection,
)
from .modeling import ConfusionMetrics
from .sessions import (
    InvalidHostTokenError,
    SessionClosedError,
    SessionNotFoundError,
    SessionStore,
    Submission,
    UnknownStudentError,
)

PROFESSOR_API_KEY = os.environ.get("PROFESSOR_API_KEY", "change-me")

app = FastAPI(
    title="EconomicsProject Deal-Likelihood Game API",
    description=(
        "Backend for the classroom game where students pick predictor variables "
        "and compete on a Shark Tank deal-likelihood logit model."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_dataset = load_prepared_dataset()
_cache = ModelCache(_dataset)
_store = SessionStore(_cache, _dataset)


# -- error mapping -----------------------------------------------------------


@app.exception_handler(SessionNotFoundError)
async def _handle_not_found(request, exc: SessionNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidHostTokenError)
async def _handle_forbidden(request, exc: InvalidHostTokenError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(UnknownStudentError)
async def _handle_unauthorized(request, exc: UnknownStudentError):
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(SessionClosedError)
async def _handle_closed(request, exc: SessionClosedError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# -- auth / validation helpers ------------------------------------------------


def require_professor_key(x_professor_key: str = Header(...)) -> None:
    if not secrets.compare_digest(x_professor_key, PROFESSOR_API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid professor key")


def _validate_variables(variables: list[str]) -> None:
    try:
        validate_variable_selection(variables)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _metrics_dict(metrics: ConfusionMetrics) -> dict:
    return {
        "accuracy": metrics.accuracy,
        "yes_deal_accuracy": metrics.yes_deal_accuracy,
        "no_deal_accuracy": metrics.no_deal_accuracy,
        "sample_size": metrics.sample_size,
    }


def _submission_dict(submission: Submission) -> dict:
    return {
        "student_id": submission.student_id,
        "full_name": submission.full_name,
        "variables": submission.variables,
        "equation": submission.equation,
        "basic_test": _metrics_dict(submission.basic_test),
        "final_test": _metrics_dict(submission.final_test) if submission.final_test else None,
        "finalized_at": submission.finalized_at,
    }


def _rank_of(submission: Submission, leaderboard: list[Submission]) -> int | None:
    for index, entry in enumerate(leaderboard, start=1):
        if entry is submission:
            return index
    return None


# -- professor: start / stop, dashboard ---------------------------------------


@app.post("/sessions", status_code=201, dependencies=[Depends(require_professor_key)])
def start_session():
    session = _store.create()
    return {"session_code": session.code, "host_token": session.host_token}


@app.get("/sessions/{code}/dashboard")
def dashboard(code: str, x_host_token: str = Header(...)):
    session = _store.require_host(code, x_host_token)
    snap = session.dashboard()
    return {
        "status": snap["status"],
        "students_online": snap["students_online"],
        "students_total": snap["students_total"],
        "students_finalized": snap["students_finalized"],
        "average_variables_chosen": snap["average_variables_chosen"],
        "leaderboard": [_submission_dict(sub) for sub in snap["leaderboard"]],
    }


@app.post("/sessions/{code}/stop")
def stop_session(code: str, x_host_token: str = Header(...)):
    session = _store.require_host(code, x_host_token)
    results = session.close()
    return {
        "status": "closed",
        "basic_test_leaderboard": [_submission_dict(sub) for sub in results.basic_test_leaderboard],
        "final_test_leaderboard": [_submission_dict(sub) for sub in results.final_test_leaderboard],
    }


# -- student: join, explore, finalize, status ---------------------------------


@app.post("/sessions/{code}/join", status_code=201)
def join_session(code: str, body: schemas.JoinRequest):
    session = _store.get(code)
    try:
        student = session.join(body.full_name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {
        "student_id": student.student_id,
        "student_token": student.token,
        "usable_columns": USABLE_COLUMNS,
        "categories": CATEGORY_VALUES,
        "dummy_column_category": DUMMY_COLUMN_CATEGORY,
    }


@app.post("/sessions/{code}/explore")
def explore(code: str, body: schemas.ExploreRequest, x_student_token: str = Header(...)):
    _validate_variables(body.variables)
    session = _store.get(code)
    fitted, already_submitted = session.explore(x_student_token, body.variables)
    if already_submitted:
        submission = session.submission_for(x_student_token)
        return {"status": "already_submitted", **_submission_dict(submission)}
    return {
        "status": "ok",
        "variables": sorted(set(body.variables)),
        "equation": fitted.equation,
        "basic_test": _metrics_dict(fitted.basic_test),
    }


@app.post("/sessions/{code}/finalize")
def finalize(code: str, body: schemas.FinalizeRequest, x_student_token: str = Header(...)):
    _validate_variables(body.variables)
    session = _store.get(code)
    submission, already_submitted = session.finalize(x_student_token, body.variables)
    return {"status": "already_submitted" if already_submitted else "ok", **_submission_dict(submission)}


@app.get("/sessions/{code}/status")
def session_status(code: str, x_student_token: str = Header(...)):
    session = _store.get(code)
    session.student_for_token(x_student_token)  # raises UnknownStudentError -> 401 if invalid

    if session.status == "open":
        return {"status": "open"}

    submission = session.submission_for(x_student_token)
    if submission is None:
        return {"status": "closed", "your_submission": None}

    return {
        "status": "closed",
        "your_submission": _submission_dict(submission),
        "your_basic_test_rank": _rank_of(submission, session.final_results.basic_test_leaderboard),
        "your_final_test_rank": _rank_of(submission, session.final_results.final_test_leaderboard),
    }
