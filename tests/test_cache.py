from economicsproject.cache import ModelCache
from economicsproject.dataset import load_prepared_dataset


def test_get_or_fit_reuses_cached_model_regardless_of_variable_order():
    dataset = load_prepared_dataset()
    cache = ModelCache(dataset)

    first = cache.get_or_fit(["Industry_Travel", "Original Ask Amount"])
    second = cache.get_or_fit(["Original Ask Amount", "Industry_Travel"])

    assert first is second
    assert cache.size() == 1


def test_get_or_fit_treats_different_variables_as_different_models():
    dataset = load_prepared_dataset()
    cache = ModelCache(dataset)

    cache.get_or_fit(["Industry_Travel"])
    cache.get_or_fit(["Original Ask Amount"])

    assert cache.size() == 2
