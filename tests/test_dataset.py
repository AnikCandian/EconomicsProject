from economicsproject.dataset import (
    CATEGORY_VALUES,
    PREPARED_DATA_PATH,
    load_prepared_dataset,
)


def test_prepared_dataset_only_has_usable_and_encoded_columns():
    dataset = load_prepared_dataset()

    assert "Industry" not in dataset.frame.columns  # replaced by dummies
    assert "Startup Name" not in dataset.frame.columns  # not a usable column
    for column, categories in CATEGORY_VALUES.items():
        dummies = dataset.category_dummy_columns[column]
        assert dummies == [f"{column}_{value}" for value in categories[1:]]
        for dummy in dummies:
            assert dummy in dataset.frame.columns


def test_prepared_csv_is_written_to_disk():
    load_prepared_dataset()
    assert PREPARED_DATA_PATH.exists()


def test_expand_passes_through_numeric_columns_unchanged():
    dataset = load_prepared_dataset()
    assert dataset.expand(["Original Ask Amount"]) == ["Original Ask Amount"]


def test_expand_turns_a_category_into_its_dummy_columns():
    dataset = load_prepared_dataset()
    assert dataset.expand(["Industry"]) == dataset.category_dummy_columns["Industry"]


def test_split_by_season_matches_train_basic_final_boundaries():
    dataset = load_prepared_dataset()
    train, basic_test, final_test = dataset.split_by_season()

    assert set(train["Season Number"].unique()) <= set(range(1, 8))
    assert set(basic_test["Season Number"].unique()) <= set(range(8, 11))
    assert set(final_test["Season Number"].unique()) == dataset.final_test_seasons
    assert not (set(final_test["Season Number"].unique()) & set(range(1, 11)))
