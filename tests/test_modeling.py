from economicsproject.dataset import load_prepared_dataset
from economicsproject.modeling import fit_logit_model, score_final_test


def test_fit_logit_model_produces_equation_and_basic_test_metrics():
    dataset = load_prepared_dataset()
    columns = dataset.expand(["Original Ask Amount", "Industry"])

    fitted = fit_logit_model(columns, dataset)

    assert fitted.equation.startswith("logit(P(Got Deal)) =")
    assert 0 <= fitted.basic_test.accuracy <= 1
    assert fitted.basic_test.sample_size > 0


def test_score_final_test_uses_only_the_reserved_seasons():
    dataset = load_prepared_dataset()
    columns = dataset.expand(["Original Ask Amount"])
    fitted = fit_logit_model(columns, dataset)

    final_metrics = score_final_test(fitted, dataset)

    assert final_metrics.sample_size == len(dataset.split_by_season()[2])
    assert 0 <= final_metrics.accuracy <= 1
