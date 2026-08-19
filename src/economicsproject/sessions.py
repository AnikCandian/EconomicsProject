"""In-memory game session state.

A ``Session`` models one professor-hosted "server": a join code, connected
students, their finalized variable choices, and (once stopped) the two
final leaderboards. All state here lives only in this process's memory --
appropriate for a single classroom session, not for durability across
restarts or multiple server processes. See API_PROTOCOL.md, "Scope and
limitations."
"""

from __future__ import annotations

import random
import secrets
import string
import threading
import time
from dataclasses import dataclass, field

from .cache import ModelCache
from .dataset import PreparedDataset
from .modeling import ConfusionMetrics, FittedModel, score_final_test

SESSION_CODE_LENGTH = 6


class SessionError(Exception):
    """Base class for session errors; server.py maps these to HTTP statuses."""


class SessionNotFoundError(SessionError):
    def __init__(self, code: str):
        super().__init__(f"No session with code {code!r}")
        self.code = code


class InvalidHostTokenError(SessionError):
    def __init__(self, code: str):
        super().__init__(f"Invalid host token for session {code!r}")
        self.code = code


class UnknownStudentError(SessionError):
    def __init__(self):
        super().__init__("Unknown or invalid student token")


class SessionClosedError(SessionError):
    def __init__(self, code: str):
        super().__init__(f"Session {code!r} has already ended")
        self.code = code


@dataclass
class Student:
    student_id: str
    full_name: str
    token: str
    joined_at: float = field(default_factory=time.time)


@dataclass
class Submission:
    student_id: str
    full_name: str
    variables: list[str]
    equation: str
    basic_test: ConfusionMetrics
    finalized_at: float = field(default_factory=time.time)
    final_test: ConfusionMetrics | None = None  # filled in once the session closes


@dataclass
class FinalResults:
    basic_test_leaderboard: list[Submission]  # sorted desc by basic_test.accuracy
    final_test_leaderboard: list[Submission]  # sorted desc by final_test.accuracy
    closed_at: float


class Session:
    def __init__(self, code: str, host_token: str, cache: ModelCache, dataset: PreparedDataset):
        self.code = code
        self.host_token = host_token
        self.status = "open"  # "open" | "closed"
        self.created_at = time.time()
        self.closed_at: float | None = None
        self.final_results: FinalResults | None = None
        self._cache = cache
        self._dataset = dataset
        self._lock = threading.RLock()
        self._students: dict[str, Student] = {}  # token -> Student
        self._submissions: dict[str, Submission] = {}  # token -> Submission

    def join(self, full_name: str) -> Student:
        full_name = full_name.strip()
        if not full_name:
            raise ValueError("full_name is required")
        with self._lock:
            student = Student(
                student_id=f"S{len(self._students) + 1}",
                full_name=full_name,
                token=secrets.token_urlsafe(24),
            )
            self._students[student.token] = student
            return student

    def student_for_token(self, token: str) -> Student:
        student = self._students.get(token)
        if student is None:
            raise UnknownStudentError()
        return student

    def submission_for(self, token: str) -> Submission | None:
        with self._lock:
            return self._submissions.get(token)

    def explore(self, token: str, variables: list[str]) -> tuple[FittedModel | None, bool]:
        """Returns (fitted_model, already_submitted)."""
        self.student_for_token(token)
        with self._lock:
            if token in self._submissions:
                return None, True
        if self.status != "open":
            raise SessionClosedError(self.code)
        return self._cache.get_or_fit(variables), False

    def finalize(self, token: str, variables: list[str]) -> tuple[Submission, bool]:
        """Returns (submission, already_submitted). Idempotent: a second call
        just returns the original submission, ignoring any new variables."""
        student = self.student_for_token(token)
        with self._lock:
            existing = self._submissions.get(token)
            if existing is not None:
                return existing, True
        if self.status != "open":
            raise SessionClosedError(self.code)

        fitted = self._cache.get_or_fit(variables)
        submission = Submission(
            student_id=student.student_id,
            full_name=student.full_name,
            variables=sorted(set(variables)),
            equation=fitted.equation,
            basic_test=fitted.basic_test,
        )
        with self._lock:
            existing = self._submissions.get(token)
            if existing is not None:
                return existing, True
            self._submissions[token] = submission
            return submission, False

    def dashboard(self) -> dict:
        """What the professor's periodic poll receives."""
        with self._lock:
            students = list(self._students.values())
            submissions = list(self._submissions.values())

        leaderboard = sorted(submissions, key=lambda sub: sub.basic_test.accuracy, reverse=True)
        variable_counts = [len(sub.variables) for sub in submissions]
        return {
            "status": self.status,
            "students_online": [{"student_id": st.student_id, "full_name": st.full_name} for st in students],
            "students_total": len(students),
            "students_finalized": len(submissions),
            "average_variables_chosen": (sum(variable_counts) / len(variable_counts)) if variable_counts else 0.0,
            "leaderboard": leaderboard,
        }

    def close(self) -> FinalResults:
        """End the session and score every finalized submission against the
        seasons 11+ final hold-out for the first time. Idempotent."""
        with self._lock:
            if self.final_results is not None:
                return self.final_results
            self.status = "closed"
            self.closed_at = time.time()
            submissions = list(self._submissions.values())

        for submission in submissions:
            fitted = self._cache.get_or_fit(submission.variables)
            submission.final_test = score_final_test(fitted, self._dataset)

        basic_leaderboard = sorted(submissions, key=lambda sub: sub.basic_test.accuracy, reverse=True)
        final_leaderboard = sorted(
            (sub for sub in submissions if sub.final_test and sub.final_test.sample_size),
            key=lambda sub: sub.final_test.accuracy,
            reverse=True,
        )

        with self._lock:
            self.final_results = FinalResults(basic_leaderboard, final_leaderboard, self.closed_at)
            return self.final_results


class SessionStore:
    """Creates sessions and looks them up by their join code."""

    def __init__(self, cache: ModelCache, dataset: PreparedDataset):
        self._cache = cache
        self._dataset = dataset
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        with self._lock:
            code = self._unique_code()
            session = Session(code, secrets.token_urlsafe(24), self._cache, self._dataset)
            self._sessions[code] = session
            return session

    def _unique_code(self) -> str:
        while True:
            code = "".join(random.choices(string.digits, k=SESSION_CODE_LENGTH))
            if code not in self._sessions:
                return code

    def get(self, code: str) -> Session:
        session = self._sessions.get(code)
        if session is None:
            raise SessionNotFoundError(code)
        return session

    def require_host(self, code: str, host_token: str) -> Session:
        session = self.get(code)
        if not secrets.compare_digest(session.host_token, host_token or ""):
            raise InvalidHostTokenError(code)
        return session
