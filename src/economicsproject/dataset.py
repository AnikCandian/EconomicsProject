"""Dataset loading and preparation for the Shark Tank deal-likelihood model.

The raw CSV (``Shark Tank US dataset.csv``) is never modified. On first use
this module derives a second, reformatted CSV next to it -- containing only
the usable columns, with every category already one-hot encoded into its own
individually-selectable column -- writes it to disk, and loads the in-memory
dataset from THAT file. Keeping the derived file on disk makes it easy to
eyeball or debug exactly what the model is trained on, without ever touching
the source data.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

RAW_DATA_PATH = Path(__file__).parent / "Shark Tank US dataset.csv"
PREPARED_DATA_PATH = Path(__file__).parent / "prepared_shark_tank_dataset.csv"

SEASON_COLUMN = "Season Number"
TARGET_COLUMN = "Got Deal"

# Seasons 1-7 train every model. Seasons 8-10 are the "basic test" shown to
# students live while they explore. Everything after that (11+) is a final
# hold-out, only ever scored once a game session ends -- see modeling.py.
TRAIN_SEASONS = set(range(1, 8))
BASIC_TEST_SEASONS = set(range(8, 11))

# Plain numeric columns students can pick as variables.
NUMERIC_USABLE_COLUMNS = [
    "Episode Number",
    "Pitch Number",
    "Multiple Entrepreneurs",
    "US Viewership",
    "Original Ask Amount",
    "Original Offered Equity",
    "Valuation Requested",
    "Barbara Corcoran Present",
    "Mark Cuban Present",
    "Lori Greiner Present",
    "Robert Herjavec Present",
    "Daymond John Present",
    "Kevin O Leary Present",
    "Guest Present",
    "Season Number",
]

# Category columns and their full, fixed vocabulary (verified against the
# raw CSV). Each value becomes its own individually-selectable dummy column
# -- students pick out specific categories (e.g. "Industry_Travel"), not the
# whole field toggled on at once. Naming convention: "<Header>_<Value>".
CATEGORY_VALUES: dict[str, list[str]] = {
    "Industry": [
        "Food and Beverage",
        "Lifestyle/Home",
        "Fashion/Beauty",
        "Fitness/Sports/Outdoors",
        "Children/Education",
        "Health/Wellness",
        "Technology/Software",
        "Pet Products",
        "Business Services",
        "Media/Entertainment",
        "Uncertain/Other",
        "Electronics",
        "Automotive",
        "Green/CleanTech",
        "Liquor/Alcohol",
        "Travel",
    ],
    "Pitchers Gender": ["Male", "Female", "Mixed Team"],
}


def _dummy_column_name(category: str, value: str) -> str:
    return f"{category}_{value}"


# Every individually-selectable one-hot column, in CATEGORY_VALUES order.
_CATEGORY_DUMMY_COLUMNS: list[str] = [
    _dummy_column_name(category, value)
    for category, values in CATEGORY_VALUES.items()
    for value in values
]

# The full menu of variables a student may pick from.
USABLE_COLUMNS: list[str] = NUMERIC_USABLE_COLUMNS + _CATEGORY_DUMMY_COLUMNS

# Reverse lookup: which original category a given dummy column belongs to.
# Used to guard against selecting every category of one field at once (see
# validate_variable_selection).
DUMMY_COLUMN_CATEGORY: dict[str, str] = {
    _dummy_column_name(category, value): category
    for category, values in CATEGORY_VALUES.items()
    for value in values
}


def validate_variable_selection(variables: list[str]) -> None:
    """Raise ValueError if any name in ``variables`` isn't a real, usable column.

    Deliberately does NOT reject selecting every category of one field at
    once (e.g. all 16 Industry values) -- that's numerically degenerate
    (see modeling.describe_collinearity) but not disallowed. Letting a
    student pick it and see *why* the resulting model is meaningless is a
    better lesson than silently blocking the option.
    """
    unusable = sorted(set(variables) - set(USABLE_COLUMNS))
    if unusable:
        raise ValueError(f"Not usable column(s): {unusable}")


def fully_selected_categories(variables: list[str]) -> list[str]:
    """Which category fields (if any) have every one of their values present
    in ``variables`` -- the classic one-hot dummy-variable trap."""
    chosen = set(variables)
    return [
        category
        for category, values in CATEGORY_VALUES.items()
        if {_dummy_column_name(category, value) for value in values} <= chosen
    ]


def one_hot_encode_categories(df: pd.DataFrame, category_values: dict[str, list[str]]) -> pd.DataFrame:
    """One-hot encode each column in ``category_values`` into individually-named dummies.

    Every category gets its own 0/1 column (e.g. "Industry" becomes
    "Industry_Technology/Software", "Industry_Food and Beverage", ... -- all
    of them, not N-1). The original category column is replaced by its
    dummies.
    """
    df = df.copy()
    for column, categories in category_values.items():
        typed = pd.Categorical(df[column], categories=categories)
        dummies = pd.get_dummies(typed, prefix=column, dtype=float)
        dummies.index = df.index
        expected = [_dummy_column_name(column, value) for value in categories]
        assert list(dummies.columns) == expected, f"unexpected dummy columns for {column!r}"
        df = pd.concat([df.drop(columns=[column]), dummies], axis=1)
    return df


@dataclass(frozen=True)
class PreparedDataset:
    """The Shark Tank data, ready to model with: usable columns only, categories
    already one-hot encoded into individually-selectable columns."""

    frame: pd.DataFrame
    feature_columns: list[str]
    final_test_seasons: frozenset[int]

    def split_by_season(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Return (train, basic_test, final_test) DataFrames split by season."""
        train = self.frame[self.frame[SEASON_COLUMN].isin(TRAIN_SEASONS)]
        basic_test = self.frame[self.frame[SEASON_COLUMN].isin(BASIC_TEST_SEASONS)]
        final_test = self.frame[self.frame[SEASON_COLUMN].isin(self.final_test_seasons)]
        return train, basic_test, final_test


def _build_prepared_frame(raw_csv_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(raw_csv_path)
    df = raw[NUMERIC_USABLE_COLUMNS + list(CATEGORY_VALUES) + [TARGET_COLUMN]].copy()
    df = df.dropna(subset=[TARGET_COLUMN])
    return one_hot_encode_categories(df, CATEGORY_VALUES)


def ensure_prepared_csv(
    raw_csv_path: Path = RAW_DATA_PATH, prepared_csv_path: Path = PREPARED_DATA_PATH
) -> Path:
    """(Re)build the reformatted CSV from the raw one and write it to disk.

    The raw CSV is only ever read here, never modified. This is the
    "convert raw CSV into a usable Python object" step made visible on disk,
    mainly so it's easy to debug exactly what a model is trained on.
    """
    df = _build_prepared_frame(raw_csv_path)
    prepared_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(prepared_csv_path, index=False)
    return prepared_csv_path


@lru_cache(maxsize=None)
def load_prepared_dataset(
    raw_csv_path: Path = RAW_DATA_PATH, prepared_csv_path: Path = PREPARED_DATA_PATH
) -> PreparedDataset:
    """Build (or rebuild) the prepared CSV, then load it as a ``PreparedDataset``.

    Cached: this only does real work once per process. The rest of the
    backend should call this rather than touching the CSVs directly.
    """
    ensure_prepared_csv(raw_csv_path, prepared_csv_path)
    frame = pd.read_csv(prepared_csv_path)

    feature_columns = [c for c in USABLE_COLUMNS if c in frame.columns]
    final_test_seasons = frozenset(frame[SEASON_COLUMN].unique()) - TRAIN_SEASONS - BASIC_TEST_SEASONS

    return PreparedDataset(
        frame=frame,
        feature_columns=feature_columns,
        final_test_seasons=final_test_seasons,
    )
