"""Dataset loading and preparation for the Shark Tank deal-likelihood model.

The raw CSV (``Shark Tank US dataset.csv``) is never modified. On first use
this module derives a second, reformatted CSV next to it -- containing only
the usable columns, with every category column already one-hot encoded --
writes it to disk, and loads the in-memory dataset from THAT file. Keeping
the derived file on disk makes it easy to eyeball or debug exactly what the
model is trained on, without ever touching the source data.
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

# The columns this project is willing to model with. Anything else (free
# text, near-empty columns, outcome columns, etc.) is off-limits.
USABLE_COLUMNS = [
    "Episode Number",
    "Pitch Number",
    "Industry",
    "Pitchers Gender",
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

# Of the usable columns, these two hold categories rather than numbers, so
# they need one-hot encoding. Each list is the column's full, fixed set of
# known values (verified against the raw CSV) -- fixed so the resulting
# dummy columns are always the same regardless of which rows/seasons happen
# to be in a given slice of data.
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


def _dummy_column_names(category: str, categories: list[str]) -> list[str]:
    """Column names one-hot encoding ``category`` produces (first category dropped)."""
    return [f"{category}_{value}" for value in categories[1:]]


def one_hot_encode_categories(
    df: pd.DataFrame, category_values: dict[str, list[str]]
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """One-hot encode each column in ``category_values`` using its fixed vocabulary.

    The first category in each list is dropped to avoid the dummy-variable
    trap, and the original category column is replaced by its dummies.
    Returns the encoded DataFrame plus a mapping of original column name to
    the dummy columns it was expanded into.
    """
    df = df.copy()
    dummy_columns: dict[str, list[str]] = {}
    for column, categories in category_values.items():
        typed = pd.Categorical(df[column], categories=categories)
        dummies = pd.get_dummies(typed, prefix=column, drop_first=True, dtype=float)
        dummies.index = df.index
        expected = _dummy_column_names(column, categories)
        assert list(dummies.columns) == expected, f"unexpected dummy columns for {column!r}"
        dummy_columns[column] = expected
        df = pd.concat([df.drop(columns=[column]), dummies], axis=1)
    return df, dummy_columns


@dataclass(frozen=True)
class PreparedDataset:
    """The Shark Tank data, ready to model with: usable columns only, categories
    already one-hot encoded."""

    frame: pd.DataFrame
    category_dummy_columns: dict[str, list[str]]
    feature_columns: list[str]
    final_test_seasons: frozenset[int]

    def expand(self, logical_columns: list[str]) -> list[str]:
        """Expand logical column names into real columns in ``frame``.

        A category name like "Industry" expands to its dummy columns; a
        plain numeric column name passes through unchanged.
        """
        expanded: list[str] = []
        for column in logical_columns:
            expanded.extend(self.category_dummy_columns.get(column, [column]))
        return expanded

    def split_by_season(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Return (train, basic_test, final_test) DataFrames split by season."""
        train = self.frame[self.frame[SEASON_COLUMN].isin(TRAIN_SEASONS)]
        basic_test = self.frame[self.frame[SEASON_COLUMN].isin(BASIC_TEST_SEASONS)]
        final_test = self.frame[self.frame[SEASON_COLUMN].isin(self.final_test_seasons)]
        return train, basic_test, final_test


def _build_prepared_frame(raw_csv_path: Path) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    raw = pd.read_csv(raw_csv_path)
    df = raw[USABLE_COLUMNS + [TARGET_COLUMN]].copy()
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
    df, _ = _build_prepared_frame(raw_csv_path)
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

    dummy_columns = {
        column: _dummy_column_names(column, categories)
        for column, categories in CATEGORY_VALUES.items()
    }
    feature_columns = [c for c in frame.columns if c not in (SEASON_COLUMN, TARGET_COLUMN)]
    final_test_seasons = frozenset(frame[SEASON_COLUMN].unique()) - TRAIN_SEASONS - BASIC_TEST_SEASONS

    return PreparedDataset(
        frame=frame,
        category_dummy_columns=dummy_columns,
        feature_columns=feature_columns,
        final_test_seasons=final_test_seasons,
    )
