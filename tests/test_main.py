from economicsproject.main import main


def test_main_runs(capsys):
    main()
    captured = capsys.readouterr()
    assert "EconomicsProject" in captured.out
