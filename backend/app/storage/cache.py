"""Caching layer for computed results (e.g. retrieval).

Two backends, chosen by config:

* ``REDIS_URL`` set  -> ``redis`` (external cache, shared across instances).
* otherwise          -> in-process LRU (stdlib, offline, zero deps).

Values must be JSON-serializable so the same code path works for Redis and LRU.
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict

from .. import config


class Cache:
    def get(self, key: str):
        raise NotImplementedError

    def set(self, key: str, value, ttl: int | None = None) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        """Drop all entries (called when the underlying data changes)."""


class LocalLRU(Cache):
    """Thread-safe in-process LRU with a TTL (stdlib only)."""

    def __init__(self, maxsize: int | None = None, ttl: int | None = None):
        self.maxsize = config.CACHE_MAXSIZE if maxsize is None else maxsize
        self.ttl = config.CACHE_TTL if ttl is None else ttl
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple] = OrderedDict()

    def get(self, key: str):
        with self._lock:
            entry = self._data.pop(key, None)
            if entry is None:
                return None
            value, expires = entry
            if expires < time.time():
                return None
            self._data[key] = (value, expires)
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value, ttl: int | None = None) -> None:
        ttl = self.ttl if ttl is None else ttl
        with self._lock:
            self._data[key] = (value, time.time() + ttl)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class RedisCache(Cache):
    """Redis-backed cache. Requires ``pip install redis``."""

    def __init__(self, url: str):
        import redis
        self._r = redis.from_url(url, decode_responses=True)

    def get(self, key: str):
        try:
            v = self._r.get(key)
            return json.loads(v) if v is not None else None
        except Exception:
            return None

    def set(self, key: str, value, ttl: int | None = None) -> None:
        try:
            self._r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl or config.CACHE_TTL)
        except Exception:
            pass

    def clear(self) -> None:
        try:
            self._r.flushdb()
        except Exception:
            pass


_cache = None
_lock = threading.Lock()


def get_cache() -> Cache:
    """Return the configured cache singleton (Redis if configured, else LRU)."""
    global _cache
    with _lock:
        if _cache is None:
            if config.REDIS_URL:
                try:
                    _cache = RedisCache(config.REDIS_URL)
                except Exception:
                    _cache = LocalLRU()
            else:
                _cache = LocalLRU()
        return _cache
