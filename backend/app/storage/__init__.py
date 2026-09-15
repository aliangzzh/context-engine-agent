"""Persistence layer: relational store (SQLite default / MySQL optional) + cache.

* ``history_store`` — conversation history in a SQL table (replaces JSON per session).
* ``cache``         — retrieval/result cache (Redis optional, in-process LRU default).

Both are intentionally behind a tiny interface so the underlying backend can be
switched by config (``DATABASE_URL`` / ``REDIS_URL``) without touching callers.
"""
from __future__ import annotations

from .history_store import SQLChatStore
from .cache import get_cache

__all__ = ["SQLChatStore", "get_cache"]
