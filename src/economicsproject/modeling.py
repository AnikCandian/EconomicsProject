"""Fit and score logit models for the deal-likelihood game.

Every model predicts ``Got Deal`` from a chosen set of feature columns,
trained only on seasons 1-7 (see ``dataset.TRAIN_SEASONS``). Scoring against
other season ranges -- the seasons 8-10 "basic test" and the seasons 11+
"final test" -- is a separate, cheap step that reuses the fitted
coefficients rather than refitting, so a model only ever gets trained once.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .dataset import PreparedDataset, TARGET_COLUMN, fully_selected_categories, validate_variable_selection


class ModelFitError(ValueError):
    """The design matrix could not be fit at all (statsmodels itself failed).

    Distinct from a merely *degenerate* fit (see ``FittedModel.warning``),
    which still returns a result -- this is for the rarer case where the
    solver hard-fails instead of silently returning an arbitrary answer.
    """


@dataclass(frozen=True)
class ConfusionMetrics:
    """Accuracy split out by the actual outcome, plus overall accuracy."""

    accuracy: float
    yes_deal_accuracy: float | None  # of the actual deals, % predicted correctly
    no_deal_accuracy: float | None  # of the actual non-deals, % predicted correctly
    sample_size: int


@dataclass(frozen=True)
class FittedModel:
    feature_columns: list[str]  # encoded column names, in coefficient order
    coefficients: dict[str, float]  # includes "const"
    equation: str
    train_pseudo_r_squared: float
    train_means: dict[str, float]  # for imputing missing values on any other split
    basic_test: ConfusionMetrics  # seasons 8-10, computed once at fit time
    warning: str | None = None  # set when the fit is numerically degenerate -- see below


def fit_logit_model(feature_columns: list[str], dataset: PreparedDataset) -> FittedModel:
    """Fit a logit regression on seasons 1-7 and score it against seasons 8-10.

    ``feature_columns`` must be real column names in ``dataset.frame`` --
    every one-hot category is individually selectable (e.g.
    "Industry_Travel"), there's no "logical name expands to N dummies" step.
    This validates them itself (via ``dataset.validate_variable_selection``),
    so this guard holds even when called directly, outside the API.

    Selecting every category of the same one-hot field at once (e.g. all 16
    Industry values) is allowed, on purpose: it's a genuinely instructive
    failure mode. It's *not* rejected up front -- instead this still fits a
    model and returns it, but with ``FittedModel.warning`` explaining why the
    resulting coefficients aren't a real, unique answer. See
    ``describe_collinearity`` for the reasoning.
    """
    validate_variable_selection(feature_columns)
    train_df, basic_test_df, _ = dataset.split_by_season()

    train_means = train_df[feature_columns].mean().to_dict()
    train_df = train_df.fillna(train_means)

    X_train = sm.add_constant(train_df[feature_columns], has_constant="add")
    y_train = train_df[TARGET_COLUMN]
    warning = describe_collinearity(feature_columns, X_train)

    try:
        result = sm.Logit(y_train, X_train).fit(disp=0)
    except np.linalg.LinAlgError as exc:
        raise ModelFitError(
            f"Could not fit a model on {feature_columns!r} -- the design matrix is singular. {exc}"
        ) from exc

    coefficients = {name: float(value) for name, value in result.params.items()}

    return FittedModel(
        feature_columns=list(feature_columns),
        coefficients=coefficients,
        equation=_format_equation(coefficients, feature_columns),
        train_pseudo_r_squared=float(result.prsquared),
        train_means=train_means,
        basic_test=score(coefficients, feature_columns, train_means, basic_test_df),
        warning=warning,
    )


def describe_collinearity(feature_columns: list[str], X: pd.DataFrame) -> str | None:
    """Explain, in plain language, why a design matrix is perfectly collinear
    -- or return None if it isn't.

    Detected numerically (matrix rank < column count), not by pattern-
    matching "did they pick every category" -- so this catches the general
    case, not just the one we anticipated. Most commonly triggered by
    selecting every category of one one-hot field at once: those dummy
    columns sum to 1 for every row, exactly duplicating the intercept
    column. When that happens there's no unique best-fit answer -- an
    entire line of coefficient vectors (shift the intercept by c, shift
    every one of that field's coefficients by -c) score identically. The
    optimizer still returns *something* (it doesn't error), but which point
    on that line you get depends on the solver and its starting point, not
    on the data.

    Rank is computed via SVD (``numpy.linalg.matrix_rank``), which can
    itself fail to converge on a badly enough conditioned matrix -- e.g.
    combining many numeric columns on wildly different scales (large
    dollar amounts alongside 0/1 indicators) without any one-hot field
    being fully selected at all. Caught here rather than left to escape as
    a raw ``LinAlgError`` -- this used to crash `fit_logit_model()` before
    reaching its own ``try/except`` a few lines down, which only wraps the
    *fit* call, not this rank check (verified: reproduces with just
    ``NUMERIC_USABLE_COLUMNS`` selected, no ``Industry_*`` involved at
    all). See API_PROTOCOL.md, "Degenerate fits."
    """
    try:
        is_full_rank = np.linalg.matrix_rank(X.to_numpy()) >= X.shape[1]
    except np.linalg.LinAlgError:
        return (
            "This variable set is numerically unstable: computing the design "
            "matrix's rank itself failed to converge, which happens when "
            "columns on wildly different scales (or otherwise badly "
            "conditioned data) push the underlying linear algebra past what "
            "it can reliably solve. Any fit on this selection -- even one "
            "that appears to succeed -- shouldn't be trusted; the "
            "coefficients aren't a real, reproducible answer."
        )

    if is_full_rank:
        return None

    culprits = fully_selected_categories(feature_columns)
    if culprits:
        named = " and ".join(f"{c!r}" for c in culprits)
        cause = (
            f"every category of {named} was selected at once, so those dummy "
            "columns sum to 1 for every row -- exactly duplicating the intercept."
        )
    else:
        cause = "the selected columns are an exact linear combination of one another."

    return (
        f"This variable set is perfectly multicollinear: {cause} There is no unique "
        "best-fit answer -- the coefficients below are just one arbitrary point among "
        "infinitely many that score identically. Different solvers (or even the same "
        "solver from a different starting point) can return different numbers for the "
        "exact same data, and standard errors are undefined. Treat this as a "
        "demonstration of a broken fit, not a usable model."
    )


def score_final_test(fitted: FittedModel, dataset: PreparedDataset) -> ConfusionMetrics:
    """Score an already-fitted model against the untouched seasons 11+ data.

    Deliberately kept separate from ``fit_logit_model``: call this only once
    a game session ends, so the final hold-out stays unseen while students
    are still exploring.
    """
    _, _, final_test_df = dataset.split_by_season()
    return score(fitted.coefficients, fitted.feature_columns, fitted.train_means, final_test_df)


def score(
    coefficients: dict[str, float],
    feature_columns: list[str],
    train_means: dict[str, float],
    df: pd.DataFrame,
) -> ConfusionMetrics:
    """Confusion-matrix metrics for a fitted model's coefficients on any slice of data."""
    if df.empty:
        return ConfusionMetrics(accuracy=0.0, yes_deal_accuracy=None, no_deal_accuracy=None, sample_size=0)

    df = df.fillna(train_means)
    weights = np.array([coefficients[c] for c in feature_columns])
    log_odds = coefficients["const"] + df[feature_columns].to_numpy(dtype=float) @ weights
    probabilities = 1 / (1 + np.exp(-log_odds))
    predicted = probabilities >= 0.5
    actual = df[TARGET_COLUMN].to_numpy(dtype=float) == 1

    correct = predicted == actual
    accuracy = float(correct.mean())
    yes_deal_accuracy = float(correct[actual].mean()) if actual.any() else None
    no_deal_accuracy = float(correct[~actual].mean()) if (~actual).any() else None

    return ConfusionMetrics(
        accuracy=accuracy,
        yes_deal_accuracy=yes_deal_accuracy,
        no_deal_accuracy=no_deal_accuracy,
        sample_size=int(len(df)),
    )


def _format_equation(coefficients: dict[str, float], feature_columns: list[str]) -> str:
    """Render the fitted coefficients as a readable log-odds equation."""
    terms = [f"{coefficients['const']:.4f}"]
    for column in feature_columns:
        coefficient = coefficients[column]
        sign = "+" if coefficient >= 0 else "-"
        terms.append(f"{sign} {abs(coefficient):.4f} * {column}")
    return "logit(P(Got Deal)) = " + " ".join(terms)
