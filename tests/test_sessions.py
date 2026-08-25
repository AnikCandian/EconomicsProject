import pytest

from economicsproject.dataset import load_prepared_dataset
from economicsproject.sessions import (
    DUPLICATE_COLLAPSE_WINDOW_SECONDS,
    MAX_ATTEMPTS,
    SessionClosedError,
    SessionStore,
    UnknownStudentError,
)


@pytest.fixture
def store():
    dataset = load_prepared_dataset()
    return SessionStore(dataset)


def test_join_finalize_happy_path(store):
    session = store.create()
    student = session.join("Ada Lovelace")

    submission, finalize_status = session.finalize(student.token, ["Industry_Travel", "Original Ask Amount"])
    assert finalize_status == "ok"
    assert submission.student_id == student.student_id
    assert submission.attempt_number == 1
    assert submission.variables == ["Industry_Travel", "Original Ask Amount"]


def test_finalize_allows_up_to_max_attempts(store):
    session = store.create()
    student = session.join("Ada Lovelace")

    first, status1 = session.finalize(student.token, ["Industry_Travel"])
    second, status2 = session.finalize(student.token, ["Original Ask Amount"])
    third, status3 = session.finalize(student.token, ["Industry_Automotive"])

    assert MAX_ATTEMPTS == 3
    assert [status1, status2, status3] == ["ok", "ok", "ok"]
    assert [first.attempt_number, second.attempt_number, third.attempt_number] == [1, 2, 3]
    assert session.attempts_for(student.token) == [first, second, third]


def test_finalize_beyond_max_attempts_is_exhausted_and_unchanged(store):
    session = store.create()
    student = session.join("Ada Lovelace")

    for variables in (["Industry_Travel"], ["Original Ask Amount"], ["Industry_Automotive"]):
        session.finalize(student.token, variables)

    fourth, status = session.finalize(student.token, ["Season Number"])

    assert status == "attempts_exhausted"
    assert fourth.attempt_number == 3  # the third (last) attempt, unchanged
    assert fourth.variables == ["Industry_Automotive"]
    assert len(session.attempts_for(student.token)) == 3  # no new attempt was recorded


def test_best_attempt_for_picks_highest_basic_test_accuracy(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.finalize(student.token, ["Industry_Travel"])
    session.finalize(student.token, ["Original Ask Amount", "Original Offered Equity"])

    best = session.best_attempt_for(student.token)

    attempts = session.attempts_for(student.token)
    assert best in attempts
    assert best.basic_test.accuracy == max(a.basic_test.accuracy for a in attempts)


def test_best_attempt_for_is_none_with_no_attempts(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    assert session.best_attempt_for(student.token) is None


def test_unknown_token_is_rejected(store):
    session = store.create()
    with pytest.raises(UnknownStudentError):
        session.finalize("not-a-real-token", ["Industry_Travel"])


def test_finalize_after_close_is_rejected(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.close()

    with pytest.raises(SessionClosedError):
        session.finalize(student.token, ["Industry_Travel"])


def test_explore_is_deprecated_but_functional_and_does_not_consume_an_attempt(store):
    session = store.create()
    student = session.join("Ada Lovelace")

    fitted, explore_status = session.explore(student.token, ["Industry_Travel"])
    assert explore_status == "ok"
    assert fitted.equation.startswith("logit(P(Got Deal)) =")
    assert session.attempts_for(student.token) == []  # explore never records an attempt


def test_explore_reports_exhausted_once_max_attempts_used(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    for variables in (["Industry_Travel"], ["Original Ask Amount"], ["Industry_Automotive"]):
        session.finalize(student.token, variables)

    fitted, explore_status = session.explore(student.token, ["Season Number"])

    assert explore_status == "attempts_exhausted"
    assert fitted is None


def test_close_scores_every_attempt_and_builds_two_leaderboards_from_best_attempts(store):
    session = store.create()
    a = session.join("Ada Lovelace")
    b = session.join("Grace Hopper")
    session.finalize(a.token, ["Industry_Travel"])
    session.finalize(a.token, ["Original Ask Amount", "Original Offered Equity"])  # a's 2nd attempt
    session.finalize(b.token, ["Original Ask Amount", "Original Offered Equity"])

    results = session.close()

    # every attempt gets scored, not just the representative one
    assert all(sub.final_test is not None for sub in session.attempts_for(a.token))
    assert all(sub.final_test is not None for sub in session.attempts_for(b.token))

    # leaderboards have one entry per student (their best attempt), not one per attempt
    assert len(results.basic_test_leaderboard) == 2
    assert len(results.final_test_leaderboard) == 2

    basic_scores = [sub.basic_test.accuracy for sub in results.basic_test_leaderboard]
    assert basic_scores == sorted(basic_scores, reverse=True)
    final_scores = [sub.final_test.accuracy for sub in results.final_test_leaderboard]
    assert final_scores == sorted(final_scores, reverse=True)


def test_finalize_rejects_full_category_selection_without_consuming_an_attempt(store):
    from economicsproject.dataset import CATEGORY_VALUES

    session = store.create()
    student = session.join("Ada Lovelace")
    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]

    invalid, finalize_status = session.finalize(student.token, all_industries)

    assert finalize_status == "invalid_selection"
    assert invalid.culprit_categories == ["Industry"]
    assert "Industry" in invalid.message
    assert session.attempts_for(student.token) == []  # no attempt recorded
    assert session.invalid_selection_for(student.token) is invalid

    # a normal attempt afterward still works and is attempt #1
    submission, ok_status = session.finalize(student.token, ["Industry_Travel"])
    assert ok_status == "ok"
    assert submission.attempt_number == 1


def test_exhaustion_is_checked_before_invalid_selection(store):
    from economicsproject.dataset import CATEGORY_VALUES

    session = store.create()
    student = session.join("Ada Lovelace")
    for variables in (["Industry_Travel"], ["Original Ask Amount"], ["Industry_Automotive"]):
        session.finalize(student.token, variables)

    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]
    result, status = session.finalize(student.token, all_industries)

    # an already-exhausted student's selection is never even looked at
    assert status == "attempts_exhausted"
    assert session.invalid_selection_for(student.token) is None


def test_invalid_selection_for_is_none_before_any_rejection(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    assert session.invalid_selection_for(student.token) is None


def test_close_is_idempotent(store):
    session = store.create()
    session.join("Ada Lovelace")

    first = session.close()
    second = session.close()

    assert first is second


def test_collapse_duplicate_attempt_removes_an_identical_recent_repeat(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.finalize(student.token, ["Industry_Travel"])
    session.finalize(student.token, ["Industry_Travel"])  # identical, submitted right after

    kept, status = session.collapse_duplicate_attempt(student.token)

    assert status == "withdrawn"
    assert kept.attempt_number == 1
    remaining = session.attempts_for(student.token)
    assert len(remaining) == 1
    assert remaining[0] is kept

    # a fresh attempt afterward is #2, not #3 -- the slot was really freed
    submission, ok_status = session.finalize(student.token, ["Original Ask Amount"])
    assert ok_status == "ok"
    assert submission.attempt_number == 2


def test_collapse_duplicate_attempt_is_a_noop_with_fewer_than_two_attempts(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    assert session.collapse_duplicate_attempt(student.token) == (None, "not_eligible")

    session.finalize(student.token, ["Industry_Travel"])
    assert session.collapse_duplicate_attempt(student.token) == (None, "not_eligible")
    assert len(session.attempts_for(student.token)) == 1  # untouched


def test_collapse_duplicate_attempt_is_a_noop_when_variables_differ(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.finalize(student.token, ["Industry_Travel"])
    session.finalize(student.token, ["Original Ask Amount"])  # a real, different attempt

    kept, status = session.collapse_duplicate_attempt(student.token)

    assert (kept, status) == (None, "not_eligible")
    assert len(session.attempts_for(student.token)) == 2  # both kept


def test_collapse_duplicate_attempt_is_a_noop_outside_the_time_window(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.finalize(student.token, ["Industry_Travel"])
    session.finalize(student.token, ["Industry_Travel"])

    # push the two attempts apart in time, past the eligible window
    attempts = session.attempts_for(student.token)
    attempts[0].finalized_at -= DUPLICATE_COLLAPSE_WINDOW_SECONDS + 5

    kept, status = session.collapse_duplicate_attempt(student.token)

    assert (kept, status) == (None, "not_eligible")
    assert len(session.attempts_for(student.token)) == 2  # both kept


def test_collapse_duplicate_attempt_is_a_noop_after_close(store):
    session = store.create()
    student = session.join("Ada Lovelace")
    session.finalize(student.token, ["Industry_Travel"])
    session.finalize(student.token, ["Industry_Travel"])
    session.close()

    kept, status = session.collapse_duplicate_attempt(student.token)

    assert (kept, status) == (None, "not_eligible")
    assert len(session.attempts_for(student.token)) == 2  # untouched


def test_create_uses_the_default_season_config_when_none_given(store):
    from economicsproject.dataset import default_season_config, load_prepared_dataset

    session = store.create()
    expected = default_season_config(load_prepared_dataset().available_seasons)

    assert session.season_config == expected
    # the default deliberately tests on the training data itself
    assert session.season_config.train_seasons == session.season_config.basic_test_seasons


def test_create_accepts_a_custom_season_config(store):
    from economicsproject.dataset import SeasonConfig

    custom = SeasonConfig(
        train_seasons=frozenset(range(1, 8)),
        basic_test_seasons=frozenset(range(8, 11)),
        final_test_seasons=frozenset(range(11, 18)),
    )
    session = store.create(custom)

    assert session.season_config == custom


def test_create_rejects_an_invalid_season_config(store):
    from economicsproject.dataset import SeasonConfig

    with pytest.raises(ValueError, match="unknown season"):
        store.create(SeasonConfig(frozenset({999}), frozenset({1}), frozenset({2})))
    with pytest.raises(ValueError, match="must include at least one season"):
        store.create(SeasonConfig(frozenset(), frozenset({1}), frozenset({2})))


def test_two_sessions_with_different_season_configs_score_the_same_variables_differently(store):
    from economicsproject.dataset import SeasonConfig

    default_session = store.create()
    custom_session = store.create(
        SeasonConfig(
            train_seasons=frozenset(range(1, 8)),
            basic_test_seasons=frozenset(range(8, 11)),
            final_test_seasons=frozenset(range(11, 18)),
        )
    )

    a = default_session.join("Ada Lovelace")
    b = custom_session.join("Grace Hopper")
    sub_a, _ = default_session.finalize(a.token, ["Original Ask Amount"])
    sub_b, _ = custom_session.finalize(b.token, ["Original Ask Amount"])

    # default trains and basic-tests on the same (larger) season set;
    # the custom config's basic test is a genuinely smaller, disjoint slice
    assert sub_a.basic_test.sample_size != sub_b.basic_test.sample_size
