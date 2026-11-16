"""Tiny thread-safe in-memory TTL cache: a dict of key -> (expires_at, value).

One instance per provider. Only successful results are stored, so a failing
provider is retried on the next page load. Tests call `clear_all()` (see
tests/conftest.py) or set `enabled = False` to bypass caching.
"""

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any

_MISSING = object()
_registry: list["TTLCache"] = []


class TTLCache:
    def __init__(self, name: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.name = name
        self.clock = clock
        self.enabled = True
        self._data: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        _registry.append(self)

    def get(self, key: Hashable, default: Any = None) -> Any:
        if not self.enabled:
            return default
        with self._lock:
            entry = self._data.get(key, _MISSING)
            if entry is _MISSING:
                return default
            expires_at, value = entry
            if self.clock() >= expires_at:
                del self._data[key]
                return default
            return value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        if not self.enabled or ttl <= 0:
            return
        with self._lock:
            self._data[key] = (self.clock() + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def clear_all() -> None:
    for cache in _registry:
        cache.clear()
