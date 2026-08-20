import os

os.environ.setdefault("PROFESSOR_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

from economicsproject.server import app  # noqa: E402
from economicsproject.sessions import MAX_ATTEMPTS  # noqa: E402

client = TestClient(app)
PROFESSOR_HEADERS = {"X-Professor-Key": "test-key"}


def _start_session():
    response = client.post("/sessions", headers=PROFESSOR_HEADERS)
    assert response.status_code == 201
    return response.json()


def _join(code, name="Ada Lovelace"):
    response = client.post(f"/sessions/{code}/join", json={"full_name": name})
    assert response.status_code == 201
    return response.json()


def test_start_session_requires_professor_key():
    response = client.post("/sessions")
    assert response.status_code in (401, 422)  # 422: header missing entirely

    wrong_key = client.post("/sessions", headers={"X-Professor-Key": "nope"})
    assert wrong_key.status_code == 401


def test_full_game_flow_with_three_attempts():
    assert MAX_ATTEMPTS == 3

    session = _start_session()
    code, host_token = session["session_code"], session["host_token"]

    student = _join(code)
    token = student["student_token"]
    assert "Industry_Travel" in student["usable_columns"]
    assert student["max_attempts"] == 3
    headers = {"X-Student-Token": token}

    # attempt 1
    first = client.post(f"/sessions/{code}/finalize", json={"variables": ["Industry_Travel"]}, headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["status"] == "ok"
    assert first_body["attempt_number"] == 1
    assert first_body["attempts_used"] == 1
    assert first_body["attempts_remaining"] == 2

    # poll /attempts -- the client is meant to trust this, not the POST response
    polled = client.get(f"/sessions/{code}/attempts", headers=headers)
    assert polled.status_code == 200
    polled_body = polled.json()
    assert polled_body["attempts_used"] == 1
    assert len(polled_body["attempts"]) == 1

    # attempts 2 and 3
    client.post(f"/sessions/{code}/finalize", json={"variables": ["Original Ask Amount"]}, headers=headers)
    third = client.post(
        f"/sessions/{code}/finalize", json={"variables": ["Industry_Automotive"]}, headers=headers
    )
    assert third.json()["attempt_number"] == 3
    assert third.json()["attempts_remaining"] == 0

    # a 4th attempt is refused, not silently recomputed
    fourth = client.post(f"/sessions/{code}/finalize", json={"variables": ["Guest Present"]}, headers=headers)
    assert fourth.status_code == 200
    fourth_body = fourth.json()
    assert fourth_body["status"] == "attempts_exhausted"
    assert fourth_body["attempt_number"] == 3  # unchanged, still the 3rd attempt
    assert fourth_body["variables"] == ["Industry_Automotive"]

    all_attempts = client.get(f"/sessions/{code}/attempts", headers=headers).json()
    assert all_attempts["attempts_used"] == 3
    assert all_attempts["attempts_remaining"] == 0
    assert len(all_attempts["attempts"]) == 3

    dashboard = client.get(f"/sessions/{code}/dashboard", headers={"X-Host-Token": host_token})
    assert dashboard.status_code == 200
    dash_body = dashboard.json()
    assert dash_body["students_finalized"] == 1  # one student, not one row per attempt

    stop = client.post(f"/sessions/{code}/stop", headers={"X-Host-Token": host_token})
    assert stop.status_code == 200
    stopped = stop.json()
    assert len(stopped["basic_test_leaderboard"]) == 1
    assert len(stopped["final_test_leaderboard"]) == 1

    student_status = client.get(f"/sessions/{code}/status", headers=headers)
    assert student_status.status_code == 200
    status_body = student_status.json()
    assert status_body["status"] == "closed"
    assert len(status_body["your_attempts"]) == 3
    assert all(a["final_test"] is not None for a in status_body["your_attempts"])
    assert status_body["your_basic_test_rank"] == 1


def test_finalize_rejects_unusable_column():
    session = _start_session()
    code = session["session_code"]
    student = _join(code)

    response = client.post(
        f"/sessions/{code}/finalize",
        json={"variables": ["Startup Name"]},
        headers={"X-Student-Token": student["student_token"]},
    )
    assert response.status_code == 400
    # a bad request shouldn't consume an attempt
    attempts = client.get(f"/sessions/{code}/attempts", headers={"X-Student-Token": student["student_token"]})
    assert attempts.json()["attempts_used"] == 0


def test_selecting_every_category_of_a_field_is_rejected_and_does_not_consume_an_attempt():
    from economicsproject.dataset import CATEGORY_VALUES

    session = _start_session()
    code = session["session_code"]
    student = _join(code)
    headers = {"X-Student-Token": student["student_token"]}
    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]

    response = client.post(f"/sessions/{code}/finalize", json={"variables": all_industries}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid_selection"
    assert body["culprit_categories"] == ["Industry"]
    assert "Industry" in body["message"]
    assert body["attempts_used"] == 0
    assert body["attempts_remaining"] == 3

    # doesn't consume an attempt
    attempts = client.get(f"/sessions/{code}/attempts", headers=headers)
    assert attempts.json()["attempts_used"] == 0

    # ...but is logged and surfaced via /status, for a client whose
    # /finalize response never arrived
    poll = client.get(f"/sessions/{code}/status", headers=headers)
    assert poll.status_code == 200
    poll_body = poll.json()
    assert poll_body["status"] == "open"
    assert poll_body["last_invalid_selection"]["culprit_categories"] == ["Industry"]

    # a normal, valid attempt still works afterward
    ok = client.post(
        f"/sessions/{code}/finalize", json={"variables": ["Industry_Travel"]}, headers=headers
    )
    assert ok.json()["status"] == "ok"
    assert ok.json()["attempt_number"] == 1


def test_explore_is_deprecated_but_still_works_and_does_not_consume_an_attempt():
    session = _start_session()
    code = session["session_code"]
    student = _join(code)
    headers = {"X-Student-Token": student["student_token"]}

    response = client.post(
        f"/sessions/{code}/explore", json={"variables": ["Industry_Travel"]}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    attempts = client.get(f"/sessions/{code}/attempts", headers=headers)
    assert attempts.json()["attempts_used"] == 0


def test_wrong_host_token_is_forbidden():
    session = _start_session()
    code = session["session_code"]

    response = client.get(f"/sessions/{code}/dashboard", headers={"X-Host-Token": "wrong"})
    assert response.status_code == 403


def test_unknown_session_code_is_404():
    response = client.post("/sessions/000000/join", json={"full_name": "Nobody"})
    assert response.status_code == 404


def test_unknown_student_token_is_401():
    session = _start_session()
    code = session["session_code"]

    response = client.post(
        f"/sessions/{code}/finalize",
        json={"variables": ["Industry_Travel"]},
        headers={"X-Student-Token": "not-a-real-token"},
    )
    assert response.status_code == 401
