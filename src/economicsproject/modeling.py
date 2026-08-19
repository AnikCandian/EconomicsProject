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

from .dataset import PreparedDataset, TARGET_COLUMN


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


def fit_logit_model(feature_columns: list[str], dataset: PreparedDataset) -> FittedModel:
    """Fit a logit regression on seasons 1-7 and score it against seasons 8-10.

    ``feature_columns`` must already be real, encoded column names -- run
    them through ``PreparedDataset.expand()`` first if they might include a
    category name like "Industry".
    """
    train_df, basic_test_df, _ = dataset.split_by_season()

    train_means = train_df[feature_columns].mean().to_dict()
    train_df = train_df.fillna(train_means)

    X_train = sm.add_constant(train_df[feature_columns], has_constant="add")
    y_train = train_df[TARGET_COLUMN]
    result = sm.Logit(y_train, X_train).fit(disp=0)
    coefficients = {name: float(value) for name, value in result.params.items()}

    return FittedModel(
        feature_columns=list(feature_columns),
        coefficients=coefficients,
        equation=_format_equation(coefficients, feature_columns),
        train_pseudo_r_squared=float(result.prsquared),
        train_means=train_means,
        basic_test=score(coefficients, feature_columns, train_means, basic_test_df),
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
