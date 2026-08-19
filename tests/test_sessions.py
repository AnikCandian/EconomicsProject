import pytest

from economicsproject.cache import ModelCache
from economicsproject.dataset import load_prepared_dataset
from economicsproject.sessions import SessionClosedError, SessionStore, UnknownStudentError


@pytest.fixture
def store():
    dataset = load_prepared_dataset()
    return SessionStore(ModelCache(dataset), dataset)


def test_join_explore_finalize_happy_path(store):
    session = store.create()
    student = session.join("Ada Lovelace")

    fitted, already = session.explore(student.token, ["Industry", "Original Ask Amount"])
    assert already is False
    assert fitted.equation.startswith("logit(P(Got Deal)) =")

    submission, already = session.finalize(student.token, ["Industry", "Original Ask Amount"])
    assert already is False
    assert submission.student_id == student.student_id
    assert submission.variables == ["Industry", "Original Ask Amount"]


def test_exploring_after_finalize_reports_already_submitted(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.finalize(student.token, ["Industry"])

    fitted, already = session.explore(student.token, ["Original Ask Amount"])

    assert already is True
    assert fitted is None


def test_finalize_is_idempotent(store):
    session = store.create()
    student = session.join("Ada Lovelace")

    first, already_first = session.finalize(student.token, ["Industry"])
    second, already_second = session.finalize(student.token, ["Original Ask Amount"])

    assert already_first is False
    assert already_second is True
    assert second is first  # the second call did not overwrite the first submission


def test_unknown_token_is_rejected(store):
    session = store.create()
    with pytest.raises(UnknownStudentError):
        session.explore("not-a-real-token", ["Industry"])


def test_explore_after_close_is_rejected(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.close()

    with pytest.raises(SessionClosedError):
        session.explore(student.token, ["Industry"])


def test_close_scores_final_test_and_builds_two_leaderboards(store):
    session = store.create()
    a = session.join("Ada Lovelace")
    b = session.join("Grace Hopper")
    session.finalize(a.token, ["Industry"])
    session.finalize(b.token, ["Original Ask Amount", "Original Offered Equity"])

    results = session.close()

    assert len(results.basic_test_leaderboard) == 2
    assert len(results.final_test_leaderboard) == 2
    assert all(sub.final_test is not None for sub in results.basic_test_leaderboard)

    basic_scores = [sub.basic_test.accuracy for sub in results.basic_test_leaderboard]
    assert basic_scores == sorted(basic_scores, reverse=True)
    final_scores = [sub.final_test.accuracy for sub in results.final_test_leaderboard]
    assert final_scores == sorted(final_scores, reverse=True)


def test_close_is_idempotent(store):
    session = store.create()
    session.join("Ada Lovelace")

    first = session.close()
    second = session.close()

    assert first is second
