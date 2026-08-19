import pytest

from economicsproject.dataset import (
    CATEGORY_VALUES,
    NUMERIC_USABLE_COLUMNS,
    PREPARED_DATA_PATH,
    USABLE_COLUMNS,
    fully_selected_categories,
    load_prepared_dataset,
    validate_variable_selection,
)


def test_every_category_value_is_individually_selectable():
    dataset = load_prepared_dataset()

    assert "Industry" not in dataset.frame.columns  # not a real column any more
    assert "Industry_Travel" in USABLE_COLUMNS
    assert "Industry_Travel" in dataset.frame.columns
    assert "Pitchers Gender_Female" in USABLE_COLUMNS
    assert "Pitchers Gender_Female" in dataset.frame.columns

    # every category value gets its own column -- none dropped as a baseline
    for column, values in CATEGORY_VALUES.items():
        for value in values:
            assert f"{column}_{value}" in dataset.frame.columns


def test_usable_columns_is_numeric_columns_plus_every_category_value():
    expected_count = len(NUMERIC_USABLE_COLUMNS) + sum(len(v) for v in CATEGORY_VALUES.values())
    assert len(USABLE_COLUMNS) == expected_count


def test_prepared_csv_is_written_to_disk():
    load_prepared_dataset()
    assert PREPARED_DATA_PATH.exists()


def test_split_by_season_matches_train_basic_final_boundaries():
    dataset = load_prepared_dataset()
    train, basic_test, final_test = dataset.split_by_season()

    assert set(train["Season Number"].unique()) <= set(range(1, 8))
    assert set(basic_test["Season Number"].unique()) <= set(range(8, 11))
    assert set(final_test["Season Number"].unique()) == dataset.final_test_seasons
    assert not (set(final_test["Season Number"].unique()) & set(range(1, 11)))


def test_validate_variable_selection_rejects_unusable_columns():
    with pytest.raises(ValueError, match="Not usable"):
        validate_variable_selection(["Startup Name"])


def test_validate_variable_selection_accepts_a_partial_category_subset():
    validate_variable_selection(["Industry_Travel", "Industry_Automotive"])  # should not raise


def test_validate_variable_selection_allows_every_category_of_one_field():
    # deliberately allowed -- see modeling.describe_collinearity for why this
    # is instead surfaced as a warning on the fitted model, not blocked here
    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]
    validate_variable_selection(all_industries)  # should not raise


def test_fully_selected_categories_detects_a_complete_field():
    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]
    assert fully_selected_categories(all_industries) == ["Industry"]


def test_fully_selected_categories_ignores_a_partial_field():
    assert fully_selected_categories(["Industry_Travel", "Industry_Automotive"]) == []
