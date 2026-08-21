"""Process-wide cache of fitted logit models, keyed by the exact set of
feature-column names used to train them.

Caching is purely in-memory and lives for the lifetime of the running
server process -- it is intentionally not persisted to disk. See
API_PROTOCOL.md ("Scope and limitations") for why.
"""

from __future__ import annotations

import threading

from .dataset import PreparedDataset
from .modeling import FittedModel, fit_logit_model


class ModelCache:
    """Fits each distinct set of logical variables at most once per process.

    Fits for the *same* key are serialized (see ``get_or_fit``); fits for
    *different* keys still run fully in parallel, so one slow fit never
    blocks unrelated ones.
    """

    def __init__(self, dataset: PreparedDataset):
        self._dataset = dataset
        self._cache_lock = threading.Lock()  # protects _cache and _key_locks themselves
        self._cache: dict[tuple[str, ...], FittedModel] = {}
        self._key_locks: dict[tuple[str, ...], threading.Lock] = {}

    @staticmethod
    def _key(logical_variables: list[str]) -> tuple[str, ...]:
        # Order and duplicates shouldn't matter -- ["A", "B"] and ["B", "A"]
        # are the same model.
        return tuple(sorted(set(logical_variables)))

    def _lock_for(self, key: tuple[str, ...]) -> threading.Lock:
        with self._cache_lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def get_or_fit(self, logical_variables: list[str]) -> FittedModel:
        key = self._key(logical_variables)

        with self._cache_lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        # A previous version of this method fit outside any per-key lock,
        # on the assumption that two threads independently fitting the
        # *same* key concurrently was merely wasted work, not unsafe --
        # "whichever result lands first in the cache wins." That assumption
        # doesn't hold in general: statsmodels'/numpy's underlying LAPACK
        # calls aren't guaranteed thread-safe under true concurrent
        # invocation on every BLAS build, and a real classroom session
        # easily produces this exact race (many students trying the same
        # "obvious" variable first, within the same second). Observed
        # symptom: an intermittent, otherwise-unreproducible
        # `LinAlgError: SVD did not converge` on a student's *first*
        # attempt at a given combination, while identical follow-up
        # attempts (now served from cache) succeeded every time.
        #
        # Fixed: fits for the same key are now serialized via a per-key
        # lock, so at most one thread ever fits a given key at a time.
        # Different keys still don't block each other -- this lock is
        # per-key, not the cache-wide `_cache_lock` above.
        with self._lock_for(key):
            with self._cache_lock:
                cached = self._cache.get(key)
            if cached is not None:
                return cached
            fitted = fit_logit_model(list(key), self._dataset)
            with self._cache_lock:
                self._cache[key] = fitted
            return fitted

    def size(self) -> int:
        with self._cache_lock:
            return len(self._cache)
