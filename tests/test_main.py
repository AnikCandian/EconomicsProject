import pandas as pd

from economicsproject.main import (
    BASIC_TEST_SEASONS,
    TRAIN_SEASONS,
    detect_category_columns,
    fit_deal_likelihood_regression,
    main,
    one_hot_encode_categories,
)


def test_main_runs(capsys):
    main()
    captured = capsys.readouterr()
    assert "EconomicsProject" in captured.out


def test_detect_category_columns_flags_only_non_numeric_columns():
    df = pd.DataFrame({"Industry": ["Tech", "Food"], "Original Ask Amount": [1000, 2000]})

    assert detect_category_columns(df, ["Industry", "Original Ask Amount"]) == ["Industry"]


def test_one_hot_encode_categories_replaces_category_column_with_dummies():
    df = pd.DataFrame({"Industry": ["Tech", "Food", "Tech"], "Got Deal": [1, 0, 1]})

    encoded = one_hot_encode_categories(df, ["Industry"])

    assert "Industry" not in encoded.columns
    dummy_columns = [c for c in encoded.columns if c.startswith("Industry_")]
    assert dummy_columns  # at least one dummy column was created
    for column in dummy_columns:
        assert set(encoded[column].unique()) <= {0.0, 1.0}


def test_fit_deal_likelihood_regression_trains_on_seasons_1_to_7():
    result = fit_deal_likelihood_regression(
        ["Original Ask Amount", "Original Offered Equity", "Industry"]
    )

    assert set(result["train_seasons"]) <= TRAIN_SEASONS
    assert set(result["basic_test_seasons"]) <= BASIC_TEST_SEASONS
    # final-test seasons are whatever's left (11+), never seen during training
    assert not (set(result["final_test_seasons"]) & TRAIN_SEASONS)
    assert not (set(result["final_test_seasons"]) & BASIC_TEST_SEASONS)

    assert result["equation"].startswith("logit(P(Got Deal)) =")
    assert result["train_pseudo_r_squared"] is not None
    assert 0 <= result["train_accuracy"] <= 1


def test_fit_deal_likelihood_regression_rejects_unknown_column():
    import pytest

    with pytest.raises(ValueError):
        fit_deal_likelihood_regression(["Not A Real Column"])
