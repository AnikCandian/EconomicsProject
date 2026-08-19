"""Entry point for the EconomicsProject package.

Run with:
    python -m economicsproject.main
"""

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


def load_dataset(csv_path: Path = DATA_PATH) -> pd.DataFrame:
    """Load the Shark Tank dataset CSV into a DataFrame."""
    return pd.read_csv(csv_path)


def detect_category_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    """Return the subset of ``columns`` that hold categories (non-numeric values)."""
    return [c for c in columns if not pd.api.types.is_numeric_dtype(df[c])]


def one_hot_encode_categories(df: pd.DataFrame, category_columns: list[str]) -> pd.DataFrame:
    """One-hot encode each column in ``category_columns``.

    Each category becomes its own 0/1 column (e.g. ``Industry`` becomes
    ``Industry_Technology/Software``, ``Industry_Food and Beverage``, ...).
    The first category of each column is dropped to avoid the dummy-variable
    trap, and the original category column is replaced by its dummies.
    """
    return pd.get_dummies(df, columns=category_columns, drop_first=True, dtype=float)


def fit_deal_likelihood_regression(feature_columns: list[str], csv_path: Path = DATA_PATH) -> dict:
    """Fit a logit (logistic) regression that estimates the likelihood of getting a deal.

    ``feature_columns`` is a list of strings naming the CSV headers to use as
    predictors (e.g. ``["Original Ask Amount", "Original Offered Equity",
    "Industry"]``). Any column holding categories (non-numeric values, e.g.
    ``Industry``) is automatically one-hot encoded via
    :func:`one_hot_encode_categories`.

    The model is trained only on seasons 1-7. Seasons 8-10 are scored as a
    basic test set, and seasons 11 onward are set aside untouched as a final
    hold-out test (their rows are returned, not evaluated here).

    Returns a dict with the fitted statsmodels Logit result, a human-readable
    log-odds equation string, McFadden's pseudo R-squared and accuracy on the
    train/basic-test splits, and the raw final-test rows for later evaluation.
    """
    df = load_dataset(csv_path)

    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Unknown column header(s): {missing}")

    df = df[[SEASON_COLUMN] + feature_columns + [TARGET_COLUMN]].copy()
    df = df.dropna(subset=[TARGET_COLUMN])

    category_columns = detect_category_columns(df, feature_columns)
    df = one_hot_encode_categories(df, category_columns)
    encoded_feature_columns = [c for c in df.columns if c not in (SEASON_COLUMN, TARGET_COLUMN)]

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
