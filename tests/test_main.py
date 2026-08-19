from economicsproject.main import main, run_demo


def test_run_demo_prints_an_equation(capsys):
    run_demo()
    captured = capsys.readouterr()
    assert "EconomicsProject" in captured.out
    assert "logit(P(Got Deal)) =" in captured.out


def test_main_demo_flag_runs_the_demo_not_the_server(capsys, monkeypatch):
    called = {}
    monkeypatch.setattr("economicsproject.main.run_server", lambda: called.setdefault("server", True))

    main(["--demo"])

    assert "server" not in called
    captured = capsys.readouterr()
    assert "EconomicsProject" in captured.out


def test_main_default_launches_the_server(monkeypatch):
    called = {}
    monkeypatch.setattr("economicsproject.main.run_server", lambda: called.setdefault("server", True))

    main([])

    assert called.get("server") is True
