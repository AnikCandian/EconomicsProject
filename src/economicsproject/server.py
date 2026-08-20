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
from .modeling import ConfusionMetrics, ModelFitError
from .sessions import (
    MAX_ATTEMPTS,
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
    version="1.1.0",
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


@app.exception_handler(ModelFitError)
async def _handle_model_fit_error(request, exc: ModelFitError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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
        "attempt_number": submission.attempt_number,
        "variables": submission.variables,
        "equation": submission.equation,
        "basic_test": _metrics_dict(submission.basic_test),
        "final_test": _metrics_dict(submission.final_test) if submission.final_test else None,
        "finalized_at": submission.finalized_at,
        "warning": submission.warning,
    }


def _rank_of(submission: Submission | None, leaderboard: list[Submission]) -> int | None:
    if submission is None:
        return None
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


# -- student: join, explore (deprecated), finalize, attempts, status ---------


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
        "max_attempts": MAX_ATTEMPTS,
    }


@app.post("/sessions/{code}/explore", deprecated=True)
def explore(code: str, body: schemas.ExploreRequest, x_student_token: str = Header(...)):
    """Deprecated: no longer called by either shipped client (see
    API_PROTOCOL.md, "Attempts"). Left in place, functional, in case this
    needs to be reverted -- it does not consume an attempt."""
    _validate_variables(body.variables)
    session = _store.get(code)
    fitted, explore_status = session.explore(x_student_token, body.variables)
    if explore_status == "attempts_exhausted":
        return {"status": "attempts_exhausted", "attempts_used": MAX_ATTEMPTS, "attempts_remaining": 0}
    return {
        "status": "ok",
        "variables": sorted(set(body.variables)),
        "equation": fitted.equation,
        "basic_test": _metrics_dict(fitted.basic_test),
        "warning": fitted.warning,
    }


@app.post("/sessions/{code}/finalize")
def finalize(code: str, body: schemas.FinalizeRequest, x_student_token: str = Header(...)):
    session = _store.get(code)
    session.student_for_token(x_student_token)  # raises UnknownStudentError -> 401 if invalid
    try:
        submission, finalize_status = session.finalize(x_student_token, body.variables)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    attempts_used = submission.attempt_number
    return {
        "status": finalize_status,  # "ok" | "attempts_exhausted"
        "attempts_used": attempts_used,
        "attempts_remaining": max(0, MAX_ATTEMPTS - attempts_used),
        "max_attempts": MAX_ATTEMPTS,
        **_submission_dict(submission),
    }


@app.get("/sessions/{code}/attempts")
def attempts(code: str, x_student_token: str = Header(...)):
    """Every attempt this student has made, oldest first -- poll this after
    POSTing to /finalize rather than trusting that response alone. Attempts
    are scarce (MAX_ATTEMPTS each) and are recorded server-side regardless
    of whether the POST response actually reaches the client, so this GET
    is the reliable way to confirm what really landed."""
    session = _store.get(code)
    session.student_for_token(x_student_token)  # raises UnknownStudentError -> 401 if invalid
    submissions = session.attempts_for(x_student_token)
    return {
        "attempts": [_submission_dict(sub) for sub in submissions],
        "attempts_used": len(submissions),
        "attempts_remaining": max(0, MAX_ATTEMPTS - len(submissions)),
        "max_attempts": MAX_ATTEMPTS,
    }


@app.get("/sessions/{code}/status")
def session_status(code: str, x_student_token: str = Header(...)):
    session = _store.get(code)
    session.student_for_token(x_student_token)  # raises UnknownStudentError -> 401 if invalid

    if session.status == "open":
        return {"status": "open"}

    best = session.best_attempt_for(x_student_token)
    return {
        "status": "closed",
        "your_attempts": [_submission_dict(sub) for sub in session.attempts_for(x_student_token)],
        "your_basic_test_rank": _rank_of(best, session.final_results.basic_test_leaderboard),
        "your_final_test_rank": _rank_of(best, session.final_results.final_test_leaderboard),
    }
