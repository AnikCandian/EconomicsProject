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
    """Fits each distinct set of logical variables at most once per process."""

    def __init__(self, dataset: PreparedDataset):
        self._dataset = dataset
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, ...], FittedModel] = {}

    @staticmethod
    def _key(logical_variables: list[str]) -> tuple[str, ...]:
        # Order and duplicates shouldn't matter -- ["A", "B"] and ["B", "A"]
        # are the same model.
        return tuple(sorted(set(logical_variables)))

    def get_or_fit(self, logical_variables: list[str]) -> FittedModel:
        key = self._key(logical_variables)

        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        # Fit outside the lock so one slow fit doesn't block unrelated keys.
        # A duplicate concurrent fit of the same key is wasted work but
        # still correct -- whichever result lands first in the cache wins.
        fitted = fit_logit_model(list(key), self._dataset)

        with self._lock:
            self._cache.setdefault(key, fitted)
            return self._cache[key]

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
