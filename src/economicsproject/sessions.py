"""In-memory game session state.

A ``Session`` models one professor-hosted "server": a join code, connected
students, their submitted attempts, and (once stopped) the two final
leaderboards. All state here lives only in this process's memory --
appropriate for a single classroom session, not for durability across
restarts or multiple server processes. See API_PROTOCOL.md, "Scope and
limitations."

Students get up to ``MAX_ATTEMPTS`` submissions each, not one -- see
API_PROTOCOL.md, "Attempts," for why. A student's "current standing" (on
the professor's dashboard, and both final leaderboards) is always their
*best* attempt so far by basic-test accuracy; ``attempts_for()`` returns
every attempt they've made, which is what the "check my previous
submissions" endpoint is for.
"""

from __future__ import annotations

import random
import secrets
import string
import threading
import time
from dataclasses import dataclass, field

from .cache import ModelCache
from .dataset import PreparedDataset, dummy_variable_trap_message, fully_selected_categories, validate_variable_selection
from .modeling import ConfusionMetrics, score_final_test

SESSION_CODE_LENGTH = 6
MAX_ATTEMPTS = 3  # per student, per session


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
    attempt_number: int  # 1-based, up to MAX_ATTEMPTS
    variables: list[str]
    equation: str
    basic_test: ConfusionMetrics
    finalized_at: float = field(default_factory=time.time)
    final_test: ConfusionMetrics | None = None  # filled in once the session closes
    warning: str | None = None  # set if this variable set is numerically degenerate


@dataclass
class InvalidSelection:
    """A rejected finalize() attempt: every category of one or more one-hot
    fields was selected at once (the dummy-variable trap -- see
    dataset.fully_selected_categories). Doesn't consume an attempt. Recorded
    per-student so GET /status can surface it to a client whose /finalize
    response never arrived -- the same lost-response problem that
    GET /attempts solves for successful submissions (see API_PROTOCOL.md,
    "Attempts")."""

    variables: list[str]
    culprit_categories: list[str]
    message: str
    attempted_at: float = field(default_factory=time.time)


@dataclass
class FinalResults:
    basic_test_leaderboard: list[Submission]  # each student's best attempt, sorted desc by basic_test.accuracy
    final_test_leaderboard: list[Submission]  # each student's best attempt, sorted desc by final_test.accuracy
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
        self._attempts: dict[str, list[Submission]] = {}  # token -> attempts, oldest first
        self._invalid_selections: dict[str, InvalidSelection] = {}  # token -> most recent rejection

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

    def attempts_for(self, token: str) -> list[Submission]:
        """Every attempt this student has made so far, oldest first."""
        with self._lock:
            return list(self._attempts.get(token, []))

    def best_attempt_for(self, token: str) -> Submission | None:
        """This student's current standing: their highest basic-test-accuracy
        attempt so far, or None if they haven't submitted at all."""
        with self._lock:
            attempts = self._attempts.get(token, [])
            return max(attempts, key=lambda sub: sub.basic_test.accuracy) if attempts else None

    def invalid_selection_for(self, token: str) -> InvalidSelection | None:
        """This student's most recent rejected (dummy-variable-trap)
        finalize() attempt, if any -- what GET /status surfaces so a client
        can learn a submission was rejected even if the /finalize response
        itself never arrived."""
        with self._lock:
            return self._invalid_selections.get(token)

    def explore(self, token: str, variables: list[str]) -> tuple[object | None, str]:
        """Deprecated (see API_PROTOCOL.md, "Attempts") but left functional
        for rollback. Returns (fitted_model, status), status one of "ok" /
        "attempts_exhausted". Doesn't consume an attempt."""
        self.student_for_token(token)
        with self._lock:
            used = len(self._attempts.get(token, []))
        if used >= MAX_ATTEMPTS:
            return None, "attempts_exhausted"
        if self.status != "open":
            raise SessionClosedError(self.code)
        return self._cache.get_or_fit(variables), "ok"

    def finalize(self, token: str, variables: list[str]) -> tuple[Submission | InvalidSelection, str]:
        """Submit an attempt. Returns (result, status), status one of:
        - "ok" -- a new Submission was recorded.
        - "attempts_exhausted" -- all MAX_ATTEMPTS used already; returns
          their most recent Submission, unchanged. Checked first, before
          any validation, so an exhausted student's input is never even
          looked at -- it wouldn't be used anyway.
        - "invalid_selection" -- every category of one or more one-hot
          fields was selected at once (the dummy-variable trap). Rejected
          before any fit is attempted and doesn't consume an attempt. See
          dataset.fully_selected_categories and API_PROTOCOL.md,
          "Attempts."
        Raises ValueError for any other unusable variable name.
        """
        student = self.student_for_token(token)
        with self._lock:
            existing = self._attempts.get(token, [])
            if len(existing) >= MAX_ATTEMPTS:
                return existing[-1], "attempts_exhausted"
        if self.status != "open":
            raise SessionClosedError(self.code)

        validate_variable_selection(variables)
        culprits = fully_selected_categories(variables)
        if culprits:
            invalid = InvalidSelection(
                variables=sorted(set(variables)),
                culprit_categories=culprits,
                message=dummy_variable_trap_message(culprits),
            )
            with self._lock:
                self._invalid_selections[token] = invalid
            return invalid, "invalid_selection"

        # The fit itself happens outside the lock so a slow fit doesn't
        # block other students; the count is re-checked and the attempt
        # committed atomically below.
        fitted = self._cache.get_or_fit(variables)

        with self._lock:
            existing = self._attempts.setdefault(token, [])
            if len(existing) >= MAX_ATTEMPTS:
                return existing[-1], "attempts_exhausted"
            if self.status != "open":
                raise SessionClosedError(self.code)
            submission = Submission(
                student_id=student.student_id,
                full_name=student.full_name,
                attempt_number=len(existing) + 1,
                variables=sorted(set(variables)),
                equation=fitted.equation,
                basic_test=fitted.basic_test,
                warning=fitted.warning,
            )
            existing.append(submission)
            return submission, "ok"

    def dashboard(self) -> dict:
        """What the professor's periodic poll receives. Each leaderboard
        entry is a student's best attempt so far, not one row per attempt."""
        with self._lock:
            students = list(self._students.values())
            best = [
                max(attempts, key=lambda sub: sub.basic_test.accuracy)
                for attempts in self._attempts.values()
                if attempts
            ]

        leaderboard = sorted(best, key=lambda sub: sub.basic_test.accuracy, reverse=True)
        variable_counts = [len(sub.variables) for sub in best]
        return {
            "status": self.status,
            "students_online": [{"student_id": st.student_id, "full_name": st.full_name} for st in students],
            "students_total": len(students),
            "students_finalized": len(best),
            "average_variables_chosen": (sum(variable_counts) / len(variable_counts)) if variable_counts else 0.0,
            "leaderboard": leaderboard,
        }

    def close(self) -> FinalResults:
        """End the session and score *every* attempt (not just each
        student's best) against the seasons 11+ final hold-out for the
        first time. Idempotent."""
        with self._lock:
            if self.final_results is not None:
                return self.final_results
            self.status = "closed"
            self.closed_at = time.time()
            all_attempts = [sub for attempts in self._attempts.values() for sub in attempts]

        for submission in all_attempts:
            fitted = self._cache.get_or_fit(submission.variables)
            submission.final_test = score_final_test(fitted, self._dataset)

        with self._lock:
            best = [
                max(attempts, key=lambda sub: sub.basic_test.accuracy)
                for attempts in self._attempts.values()
                if attempts
            ]

        basic_leaderboard = sorted(best, key=lambda sub: sub.basic_test.accuracy, reverse=True)
        final_leaderboard = sorted(
            (sub for sub in best if sub.final_test and sub.final_test.sample_size),
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
