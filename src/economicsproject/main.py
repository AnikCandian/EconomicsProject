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


def fit_deal_likelihood_regression(feature_columns: list[str], csv_path: Path = DATA_PATH) -> dict:
    """Fit a linear regression that estimates the likelihood of getting a deal.

    ``feature_columns`` is a list of strings naming the CSV headers to use as
    predictors (e.g. ``["Original Ask Amount", "Original Offered Equity",
    "Industry"]``). Non-numeric columns are automatically one-hot encoded.

    The model is trained only on seasons 1-7. Seasons 8-10 are scored as a
    basic test set, and seasons 11 onward are set aside untouched as a final
    hold-out test (their rows are returned, not evaluated here).

    Returns a dict with the fitted statsmodels OLS result, a human-readable
    equation string, R-squared on the train/basic-test splits, and the raw
    final-test rows for later evaluation.
    """
    df = load_dataset(csv_path)

    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Unknown column header(s): {missing}")

    df = df[[SEASON_COLUMN] + feature_columns + [TARGET_COLUMN]].copy()
    df = df.dropna(subset=[TARGET_COLUMN])

    categorical_columns = [c for c in feature_columns if not pd.api.types.is_numeric_dtype(df[c])]
    df = pd.get_dummies(df, columns=categorical_columns, drop_first=True, dtype=float)
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
    model = sm.OLS(y_train, X_train).fit()

    return {
        "model": model,
        "equation": _format_equation(model, encoded_feature_columns),
        "feature_columns": encoded_feature_columns,
        "train_r_squared": model.rsquared,
        "train_seasons": sorted(train_df[SEASON_COLUMN].unique().tolist()),
        "basic_test_r_squared": _score(model, basic_test_df, encoded_feature_columns),
        "basic_test_seasons": sorted(basic_test_df[SEASON_COLUMN].unique().tolist()),
        "final_test_seasons": sorted(final_test_df[SEASON_COLUMN].unique().tolist()),
        "final_test_df": final_test_df,
    }


def _score(model, subset_df: pd.DataFrame, feature_columns: list[str]):
    """R-squared of ``model`` on a held-out subset, or None if it's empty."""
    if subset_df.empty:
        return None
    X = sm.add_constant(subset_df[feature_columns], has_constant="add")
    y = subset_df[TARGET_COLUMN]
    predictions = model.predict(X)
    ss_res = ((y - predictions) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    return 1 - ss_res / ss_tot if ss_tot else None


def _format_equation(model, feature_columns: list[str]) -> str:
    """Render the fitted coefficients as a readable linear equation."""
    terms = [f"{model.params['const']:.4f}"]
    for column in feature_columns:
        coefficient = model.params[column]
        sign = "+" if coefficient >= 0 else "-"
        terms.append(f"{sign} {abs(coefficient):.4f} * {column}")
    return "Likelihood(Got Deal) = " + " ".join(terms)


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
    print(f"Train R^2 (seasons {result['train_seasons']}): {result['train_r_squared']:.4f}")
    print(f"Basic test R^2 (seasons {result['basic_test_seasons']}): {result['basic_test_r_squared']:.4f}")
    print(f"Final test held out for seasons: {result['final_test_seasons']}")


if __name__ == "__main__":
    main()
