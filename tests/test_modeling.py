from economicsproject.dataset import CATEGORY_VALUES, load_prepared_dataset
from economicsproject.modeling import describe_collinearity, fit_logit_model, score_final_test
import statsmodels.api as sm


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


def test_score_final_test_uses_only_the_reserved_seasons():
    dataset = load_prepared_dataset()
    fitted = fit_logit_model(["Original Ask Amount"], dataset)

    final_metrics = score_final_test(fitted, dataset)

    assert final_metrics.sample_size == len(dataset.split_by_season()[2])
    assert 0 <= final_metrics.accuracy <= 1
