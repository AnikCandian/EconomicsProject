"""Entry point for the EconomicsProject package.

Run with:
    python -m economicsproject.main
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
import statsmodels.api as sm

DATA_PATH = Path(__file__).parent / "Shark Tank US dataset.csv"
SEASON_COLUMN = "Season Number"
TARGET_COLUMN = "Got Deal"

# Seasons 1-7 train the model, seasons 8-10 are a basic hold-out test set,
# and every season after that (11+) is reserved untouched for a final test.
TRAIN_SEASONS = set(range(1, 8))
BASIC_TEST_SEASONS = set(range(8, 11))

# The columns this project models with. Anything not in this list is
# considered unusable (too sparse, free text, an outcome column, etc.).
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
# known values -- fixed so the resulting dummy columns are always the same
# regardless of which seasons happen to be in a given split.
CATEGORY_VALUES = {
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


@dataclass
class PreparedDataset:
    """The Shark Tank CSV boiled down to a ready-to-model object.

    ``frame`` holds only the usable columns (see ``USABLE_COLUMNS``), with
    every category column already expanded into 0/1 dummy columns.
    ``category_dummy_columns`` maps each original category column name (e.g.
    "Industry") to the list of dummy columns it became.
    """

    frame: pd.DataFrame
    category_dummy_columns: dict[str, list[str]]

    def expand(self, logical_columns: list[str]) -> list[str]:
        """Expand logical column names into actual columns in ``frame``.

        A category name like "Industry" expands to its dummy columns; a
        plain numeric column name passes through unchanged.
        """
        expanded: list[str] = []
        for column in logical_columns:
            expanded.extend(self.category_dummy_columns.get(column, [column]))
        return expanded


def one_hot_encode_categories(
    df: pd.DataFrame, category_values: dict[str, list[str]]
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """One-hot encode each column in ``category_values`` using its fixed vocabulary.

    Each category becomes its own 0/1 column (e.g. ``Industry`` becomes
    ``Industry_Technology/Software``, ``Industry_Food and Beverage``, ...).
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
        dummy_columns[column] = list(dummies.columns)
        df = pd.concat([df.drop(columns=[column]), dummies], axis=1)
    return df, dummy_columns


@lru_cache(maxsize=None)
def prepare_dataset(csv_path: Path = DATA_PATH) -> PreparedDataset:
    """Load the raw CSV once and turn it into a ready-to-model ``PreparedDataset``.

    This is the "convert the raw CSV into a usable Python object" step:
    restrict to ``USABLE_COLUMNS``, drop rows with no recorded deal outcome,
    and one-hot encode the category columns up front so every downstream fit
    just selects columns instead of re-encoding the data each time.
    """
    raw = pd.read_csv(csv_path)
    df = raw[USABLE_COLUMNS + [TARGET_COLUMN]].copy()
    df = df.dropna(subset=[TARGET_COLUMN])
    df, dummy_columns = one_hot_encode_categories(df, CATEGORY_VALUES)
    return PreparedDataset(frame=df, category_dummy_columns=dummy_columns)


def fit_deal_likelihood_regression(
    feature_columns: list[str], dataset: PreparedDataset | None = None
) -> dict:
    """Fit a logit (logistic) regression that estimates the likelihood of getting a deal.

    ``feature_columns`` is a list of strings naming which usable columns to
    use as predictors (e.g. ``["Original Ask Amount", "Original Offered
    Equity", "Industry"]``). "Industry" and "Pitchers Gender" are category
    names that expand to their pre-built dummy columns automatically.

    The model is trained only on seasons 1-7. Seasons 8-10 are scored as a
    basic test set, and seasons 11 onward are set aside untouched as a final
    hold-out test (their rows are returned, not evaluated here).

    Returns a dict with the fitted statsmodels Logit result, a human-readable
    log-odds equation string, McFadden's pseudo R-squared and accuracy on the
    train/basic-test splits, and the raw final-test rows for later evaluation.
    """
    dataset = dataset or prepare_dataset()

    unknown = [c for c in feature_columns if c not in USABLE_COLUMNS]
    if unknown:
        raise ValueError(f"Unknown or unusable column header(s): {unknown}")

    encoded_feature_columns = dataset.expand(feature_columns)
    df = dataset.frame

    train_df = df[df[SEASON_COLUMN].isin(TRAIN_SEASONS)]
    basic_test_df = df[df[SEASON_COLUMN].isin(BASIC_TEST_SEASONS)]
    final_test_df = df[~df[SEASON_COLUMN].isin(TRAIN_SEASONS | BASIC_TEST_SEASONS)]

    # Fill missing feature values using the training set's own averages, so
    # nothing from the test/final-test seasons leaks into the imputation.
    train_means = train_df[encoded_feature_columns].mean()
    train_df = train_df.fillna(train_means)
    basic_test_df = basic_test_df.fillna(train_means)
    final_test_df = final_test_df.fillna(train_means)

    X_train = sm.add_constant(train_df[encoded_feature_columns], has_constant="add")
    y_train = train_df[TARGET_COLUMN]
    model = sm.Logit(y_train, X_train).fit(disp=0)

    return {
        "model": model,
        "equation": _format_equation(model, encoded_feature_columns),
        "feature_columns": encoded_feature_columns,
        "train_pseudo_r_squared": model.prsquared,
        "train_accuracy": _accuracy(model, train_df, encoded_feature_columns),
        "train_seasons": sorted(train_df[SEASON_COLUMN].unique().tolist()),
        "basic_test_accuracy": _accuracy(model, basic_test_df, encoded_feature_columns),
        "basic_test_seasons": sorted(basic_test_df[SEASON_COLUMN].unique().tolist()),
        "final_test_seasons": sorted(final_test_df[SEASON_COLUMN].unique().tolist()),
        "final_test_df": final_test_df,
    }


def _accuracy(model, subset_df: pd.DataFrame, feature_columns: list[str]):
    """Classification accuracy (0.5 threshold) of ``model`` on a subset, or None if empty."""
    if subset_df.empty:
        return None
    X = sm.add_constant(subset_df[feature_columns], has_constant="add")
    y = subset_df[TARGET_COLUMN]
    predicted_probabilities = model.predict(X)
    predicted_labels = (predicted_probabilities >= 0.5).astype(float)
    return (predicted_labels == y).mean()


def _format_equation(model, feature_columns: list[str]) -> str:
    """Render the fitted coefficients as a readable log-odds equation."""
    terms = [f"{model.params['const']:.4f}"]
    for column in feature_columns:
        coefficient = model.params[column]
        sign = "+" if coefficient >= 0 else "-"
        terms.append(f"{sign} {abs(coefficient):.4f} * {column}")
    return "logit(P(Got Deal)) = " + " ".join(terms)


def main() -> None:
    print("EconomicsProject environment is set up and working!")

    example_columns = [
        "Original Ask Amount",
        "Original Offered Equity",
        "Valuation Requested",
        "Industry",
    ]
    result = fit_deal_likelihood_regression(example_columns)
    print(result["equation"])
    print(
        f"Train pseudo R^2 (seasons {result['train_seasons']}): "
        f"{result['train_pseudo_r_squared']:.4f}, accuracy: {result['train_accuracy']:.4f}"
    )
    print(
        f"Basic test accuracy (seasons {result['basic_test_seasons']}): "
        f"{result['basic_test_accuracy']:.4f}"
    )
    print(f"Final test held out for seasons: {result['final_test_seasons']}")


if __name__ == "__main__":
    main()
