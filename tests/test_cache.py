import threading

import economicsproject.cache as cache_module
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


def test_get_or_fit_never_fits_the_same_key_twice_concurrently(monkeypatch):
    # Regression test: get_or_fit() used to fit outside any per-key lock,
    # on the assumption that two threads independently fitting the *same*
    # key concurrently was merely wasted work, not unsafe. In practice this
    # produced an intermittent, otherwise-unreproducible
    # `LinAlgError: SVD did not converge` on a student's first attempt at a
    # given combination (statsmodels/numpy's LAPACK calls aren't
    # guaranteed thread-safe under true concurrent invocation on every
    # BLAS build) -- while identical follow-up attempts, served from
    # cache, always succeeded. This forces genuine overlap (a sleep inside
    # a patched fit_logit_model) to prove only one fit ever happens for a
    # given key, no matter how many threads race for it.
    dataset = load_prepared_dataset()
    cache = ModelCache(dataset)
    real_fit_logit_model = cache_module.fit_logit_model

    call_count = {"n": 0}
    count_lock = threading.Lock()

    def slow_fit(feature_columns, ds):
        with count_lock:
            call_count["n"] += 1
        threading.Event().wait(0.2)  # widen the race window
        return real_fit_logit_model(feature_columns, ds)

    monkeypatch.setattr(cache_module, "fit_logit_model", slow_fit)

    results = []
    results_lock = threading.Lock()

    def worker():
        result = cache.get_or_fit(["Original Ask Amount", "Industry_Travel"])
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert call_count["n"] == 1
    assert len(results) == 10
    assert all(r is results[0] for r in results)  # every caller got the one real fit


def test_get_or_fit_does_not_serialize_unrelated_keys(monkeypatch):
    # The per-key lock must not degrade into a de facto global lock --
    # different keys should still fit fully in parallel. A barrier that
    # needs both threads to arrive "at the same time" proves they're
    # genuinely running concurrently; if get_or_fit accidentally serialized
    # everything, one thread would still be waiting on the *other* key's
    # fit to finish before it even starts its own, and the barrier would
    # time out.
    dataset = load_prepared_dataset()
    cache = ModelCache(dataset)
    real_fit_logit_model = cache_module.fit_logit_model
    barrier = threading.Barrier(2, timeout=5)
    errors = []

    def synchronized_fit(feature_columns, ds):
        barrier.wait()
        return real_fit_logit_model(feature_columns, ds)

    monkeypatch.setattr(cache_module, "fit_logit_model", synchronized_fit)

    def worker(variables):
        try:
            cache.get_or_fit(variables)
        except Exception as exc:  # noqa: BLE001 -- captured to fail the test with context
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(["Original Ask Amount"],))
    t2 = threading.Thread(target=worker, args=(["Industry_Travel"],))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"different-key fits should run concurrently, not serialize against each other: {errors}"
    assert cache.size() == 2
