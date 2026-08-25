import pytest

from economicsproject.dataset import (
    CATEGORY_VALUES,
    NUMERIC_USABLE_COLUMNS,
    PITCHERS_GENDER_VALUES,
    PREPARED_DATA_PATH,
    USABLE_COLUMNS,
    SeasonConfig,
    default_season_config,
    fully_selected_categories,
    load_prepared_dataset,
    validate_season_config,
    validate_variable_selection,
)


def test_every_category_value_is_individually_selectable():
    dataset = load_prepared_dataset()

    assert "Industry" not in dataset.frame.columns  # not a real column any more
    assert "Industry_Travel" in USABLE_COLUMNS
    assert "Industry_Travel" in dataset.frame.columns

    # every category value gets its own column -- none dropped as a baseline
    for column, values in CATEGORY_VALUES.items():
        for value in values:
            assert f"{column}_{value}" in dataset.frame.columns


def test_pitchers_gender_is_a_single_continuous_column_not_one_hot():
    dataset = load_prepared_dataset()

    assert "Pitchers Gender" in USABLE_COLUMNS
    assert "Pitchers Gender" in NUMERIC_USABLE_COLUMNS
    assert "Pitchers Gender" not in CATEGORY_VALUES
    assert "Pitchers Gender" in dataset.frame.columns
    # not one-hot -- no per-value dummy columns
    assert "Pitchers Gender_Male" not in dataset.frame.columns
    assert "Pitchers Gender_Female" not in dataset.frame.columns
    assert "Pitchers Gender_Mixed Team" not in dataset.frame.columns

    assert PITCHERS_GENDER_VALUES == {"Male": 0.0, "Mixed Team": 0.5, "Female": 1.0}
    observed = set(dataset.frame["Pitchers Gender"].dropna().unique())
    assert observed <= {0.0, 0.5, 1.0}


def test_usable_columns_is_numeric_columns_plus_every_category_value():
    expected_count = len(NUMERIC_USABLE_COLUMNS) + sum(len(v) for v in CATEGORY_VALUES.values())
    assert len(USABLE_COLUMNS) == expected_count


def test_prepared_csv_is_written_to_disk():
    load_prepared_dataset()
    assert PREPARED_DATA_PATH.exists()


def test_default_season_config_trains_and_basic_tests_on_the_same_seasons():
    dataset = load_prepared_dataset()
    default = default_season_config(dataset.available_seasons)

    # deliberate overlap -- see dataset.default_season_config's docstring
    assert default.train_seasons == default.basic_test_seasons == frozenset(range(1, 11))
    assert default.final_test_seasons == frozenset(range(11, 18))
    # final test is whatever's left, never overlapping train by construction
    assert not (default.final_test_seasons & default.train_seasons)


def test_split_by_season_matches_a_custom_season_config():
    dataset = load_prepared_dataset()
    season_config = SeasonConfig(
        train_seasons=frozenset(range(1, 8)),
        basic_test_seasons=frozenset(range(8, 11)),
        final_test_seasons=frozenset(range(11, 18)),
    )
    train, basic_test, final_test = dataset.split_by_season(season_config)

    assert set(train["Season Number"].unique()) <= set(range(1, 8))
    assert set(basic_test["Season Number"].unique()) <= set(range(8, 11))
    assert set(final_test["Season Number"].unique()) == season_config.final_test_seasons
    assert not (set(final_test["Season Number"].unique()) & set(range(1, 11)))


def test_split_by_season_allows_train_and_basic_test_to_overlap():
    dataset = load_prepared_dataset()
    default = default_season_config(dataset.available_seasons)
    train, basic_test, _ = dataset.split_by_season(default)

    # the default deliberately tests on the training data itself
    assert len(train) == len(basic_test)
    assert set(train["Season Number"].unique()) == set(basic_test["Season Number"].unique())


def test_validate_season_config_rejects_empty_or_unknown_seasons():
    dataset = load_prepared_dataset()

    with pytest.raises(ValueError, match="must include at least one season"):
        validate_season_config(
            SeasonConfig(frozenset(), frozenset({1}), frozenset({2})), dataset.available_seasons
        )

    with pytest.raises(ValueError, match="unknown season"):
        validate_season_config(
            SeasonConfig(frozenset({999}), frozenset({1}), frozenset({2})), dataset.available_seasons
        )


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
