import pandas as pd
import pytest

from economicsproject.main import (
    BASIC_TEST_SEASONS,
    CATEGORY_VALUES,
    TRAIN_SEASONS,
    USABLE_COLUMNS,
    fit_deal_likelihood_regression,
    main,
    one_hot_encode_categories,
    prepare_dataset,
)


def test_main_runs(capsys):
    main()
    captured = capsys.readouterr()
    assert "EconomicsProject" in captured.out


def test_one_hot_encode_categories_replaces_category_column_with_fixed_dummies():
    df = pd.DataFrame({"Industry": ["Travel", "Automotive", "Travel"], "Got Deal": [1, 0, 1]})

    encoded, dummy_columns = one_hot_encode_categories(df, {"Industry": CATEGORY_VALUES["Industry"]})

    assert "Industry" not in encoded.columns
    # every known Industry category gets a dummy column (minus the dropped first one),
    # regardless of which categories actually appear in this particular slice of rows
    assert dummy_columns["Industry"] == [f"Industry_{c}" for c in CATEGORY_VALUES["Industry"][1:]]
    for column in dummy_columns["Industry"]:
        assert set(encoded[column].unique()) <= {0.0, 1.0}


def test_prepare_dataset_only_keeps_usable_columns():
    dataset = prepare_dataset()

    assert "Industry" not in dataset.frame.columns  # replaced by dummies
    assert "Startup Name" not in dataset.frame.columns  # not a usable column
    for column in USABLE_COLUMNS:
        if column in CATEGORY_VALUES:
            assert dataset.category_dummy_columns[column]
        else:
            assert column in dataset.frame.columns


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


def test_fit_deal_likelihood_regression_rejects_unusable_column():
    with pytest.raises(ValueError):
        fit_deal_likelihood_regression(["Not A Real Column"])
