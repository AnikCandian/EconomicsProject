import pytest

from economicsproject.dataset import CATEGORY_VALUES, load_prepared_dataset
from economicsproject.modeling import fit_logit_model, score_final_test


def test_fit_logit_model_produces_equation_and_basic_test_metrics():
    dataset = load_prepared_dataset()
    columns = ["Original Ask Amount", "Industry_Food and Beverage", "Industry_Travel"]

    fitted = fit_logit_model(columns, dataset)

    assert fitted.equation.startswith("logit(P(Got Deal)) =")
    assert "Industry_Food and Beverage" in fitted.equation
    assert 0 <= fitted.basic_test.accuracy <= 1
    assert fitted.basic_test.sample_size > 0


def test_fit_logit_model_rejects_a_full_category_selection():
    dataset = load_prepared_dataset()
    all_industries = [f"Industry_{value}" for value in CATEGORY_VALUES["Industry"]]

    with pytest.raises(ValueError, match="unsolvable"):
        fit_logit_model(all_industries, dataset)


def test_score_final_test_uses_only_the_reserved_seasons():
    dataset = load_prepared_dataset()
    fitted = fit_logit_model(["Original Ask Amount"], dataset)

    final_metrics = score_final_test(fitted, dataset)

    assert final_metrics.sample_size == len(dataset.split_by_season()[2])
    assert 0 <= final_metrics.accuracy <= 1
