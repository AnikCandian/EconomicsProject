from economicsproject.main import (
    BASIC_TEST_SEASONS,
    TRAIN_SEASONS,
    fit_deal_likelihood_regression,
    main,
)


def test_main_runs(capsys):
    main()
    captured = capsys.readouterr()
    assert "EconomicsProject" in captured.out


def test_fit_deal_likelihood_regression_trains_on_seasons_1_to_7():
    result = fit_deal_likelihood_regression(
        ["Original Ask Amount", "Original Offered Equity", "Industry"]
    )

    assert set(result["train_seasons"]) <= TRAIN_SEASONS
    assert set(result["basic_test_seasons"]) <= BASIC_TEST_SEASONS
    # final-test seasons are whatever's left (11+), never seen during training
    assert not (set(result["final_test_seasons"]) & TRAIN_SEASONS)
    assert not (set(result["final_test_seasons"]) & BASIC_TEST_SEASONS)

    assert result["equation"].startswith("Likelihood(Got Deal) =")
    assert result["train_r_squared"] is not None


def test_fit_deal_likelihood_regression_rejects_unknown_column():
    import pytest

    with pytest.raises(ValueError):
        fit_deal_likelihood_regression(["Not A Real Column"])
