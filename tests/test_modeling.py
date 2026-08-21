import pytest
import statsmodels.api as sm

from economicsproject.dataset import CATEGORY_VALUES, load_prepared_dataset
from economicsproject.modeling import ModelFitError, describe_collinearity, fit_logit_model, score_final_test


def test_fit_logit_model_produces_equation_and_basic_test_metrics():
    dataset = load_prepared_dataset()
    columns = ["Original Ask Amount", "Industry_Food and Beverage", "Industry_Travel"]

    fitted = fit_logit_model(columns, dataset)

    assert fitted.equation.startswith("logit(P(Got Deal)) =")
    assert "Industry_Food and Beverage" in fitted.equation
    assert 0 <= fitted.basic_test.accuracy <= 1
    assert fitted.basic_test.sample_size > 0
    assert fitted.warning is None


def test_fit_logit_model_allows_but_warns_on_a_full_category_selection():
    # deliberately allowed, not rejected -- selecting every category is a
    # genuine (and instructive) failure mode, not an input error
    dataset = load_prepared_dataset()
    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]

    fitted = fit_logit_model(all_industries, dataset)

    assert fitted.equation.startswith("logit(P(Got Deal)) =")  # still returns a result
    assert fitted.warning is not None
    assert "Industry" in fitted.warning
    assert "no unique" in fitted.warning.lower()


def test_describe_collinearity_is_none_for_a_well_posed_design_matrix():
    dataset = load_prepared_dataset()
    train_df, _, _ = dataset.split_by_season()
    columns = ["Original Ask Amount", "Industry_Travel"]
    X = sm.add_constant(train_df[columns], has_constant="add")

    assert describe_collinearity(columns, X) is None


def test_fit_logit_model_never_raises_a_raw_linalgerror_on_all_numeric_columns():
    # Regression test: numpy.linalg.matrix_rank's SVD used to fail to
    # converge on this exact selection (no one-hot field involved at all)
    # and escape describe_collinearity() as a raw LinAlgError, before
    # fit_logit_model()'s own try/except (which only wraps the .fit() call)
    # ever got a chance to catch it. Should now either fit with a warning,
    # or fail cleanly as a ModelFitError -- never a bare LinAlgError.
    from economicsproject.dataset import NUMERIC_USABLE_COLUMNS

    dataset = load_prepared_dataset()
    try:
        fitted = fit_logit_model(NUMERIC_USABLE_COLUMNS, dataset)
        assert fitted.equation.startswith("logit(P(Got Deal)) =")
    except ModelFitError:
        pass  # also an acceptable outcome -- a clean, expected failure


def test_guest_present_is_not_a_usable_column():
    # Regression test: "Guest Present" has zero non-null values in both the
    # training seasons (1-7) and the basic-test seasons (8-10) -- it only
    # starts being recorded in season 15, part of the final hold-out. Any
    # selection including it used to guarantee an uncaught
    # statsmodels.tools.sm_exceptions.MissingDataError (mean-imputing from
    # an all-NaN training column is a no-op). Excluded from USABLE_COLUMNS
    # entirely rather than offered and left to crash.
    from economicsproject.dataset import USABLE_COLUMNS

    assert "Guest Present" not in USABLE_COLUMNS
    with pytest.raises(ValueError, match="Not usable"):
        fit_logit_model(["Guest Present"], load_prepared_dataset())


def test_score_final_test_uses_only_the_reserved_seasons():
    dataset = load_prepared_dataset()
    fitted = fit_logit_model(["Original Ask Amount"], dataset)

    final_metrics = score_final_test(fitted, dataset)

    assert final_metrics.sample_size == len(dataset.split_by_season()[2])
    assert 0 <= final_metrics.accuracy <= 1
