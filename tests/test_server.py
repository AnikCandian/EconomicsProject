import os

os.environ.setdefault("PROFESSOR_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

from economicsproject.server import app  # noqa: E402

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


def test_full_game_flow():
    session = _start_session()
    code, host_token = session["session_code"], session["host_token"]

    student = _join(code)
    token = student["student_token"]
    assert "Industry_Travel" in student["usable_columns"]

    explore = client.post(
        f"/sessions/{code}/explore",
        json={"variables": ["Industry_Travel", "Original Ask Amount"]},
        headers={"X-Student-Token": token},
    )
    assert explore.status_code == 200
    body = explore.json()
    assert body["status"] == "ok"
    assert 0 <= body["basic_test"]["accuracy"] <= 1

    finalize = client.post(
        f"/sessions/{code}/finalize",
        json={"variables": ["Industry_Travel", "Original Ask Amount"]},
        headers={"X-Student-Token": token},
    )
    assert finalize.status_code == 200
    assert finalize.json()["status"] == "ok"

    # exploring again after finalizing should say so, not silently recompute
    again = client.post(
        f"/sessions/{code}/explore",
        json={"variables": ["Original Offered Equity"]},
        headers={"X-Student-Token": token},
    )
    assert again.json()["status"] == "already_submitted"

    dashboard = client.get(f"/sessions/{code}/dashboard", headers={"X-Host-Token": host_token})
    assert dashboard.status_code == 200
    dash_body = dashboard.json()
    assert dash_body["students_finalized"] == 1
    assert dash_body["average_variables_chosen"] == 2

    stop = client.post(f"/sessions/{code}/stop", headers={"X-Host-Token": host_token})
    assert stop.status_code == 200
    stopped = stop.json()
    assert len(stopped["basic_test_leaderboard"]) == 1
    assert len(stopped["final_test_leaderboard"]) == 1

    student_status = client.get(f"/sessions/{code}/status", headers={"X-Student-Token": token})
    assert student_status.status_code == 200
    status_body = student_status.json()
    assert status_body["status"] == "closed"
    assert status_body["your_basic_test_rank"] == 1


def test_selecting_every_category_of_a_field_is_allowed_but_warns():
    from economicsproject.dataset import CATEGORY_VALUES

    session = _start_session()
    code = session["session_code"]
    student = _join(code)
    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]

    response = client.post(
        f"/sessions/{code}/explore",
        json={"variables": all_industries},
        headers={"X-Student-Token": student["student_token"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["warning"] is not None
    assert "Industry" in body["warning"]


def test_unusable_column_is_rejected():
    session = _start_session()
    code = session["session_code"]
    student = _join(code)

    response = client.post(
        f"/sessions/{code}/explore",
        json={"variables": ["Startup Name"]},
        headers={"X-Student-Token": student["student_token"]},
    )
    assert response.status_code == 400


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
        f"/sessions/{code}/explore",
        json={"variables": ["Industry_Travel"]},
        headers={"X-Student-Token": "not-a-real-token"},
    )
    assert response.status_code == 401
