"""Conversation history with sliding-window and summary compression.

This is the piece the original RAG project was missing: instead of dumping the
entire JSON history back into every prompt (which grows until it blows the
context window), we keep only the most recent ``max_turns`` in full and
collapse everything older into a rolling summary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..context.token_budget import token_len


@dataclass
class HistoryTurn:
    user: str
    assistant: str


class ChatStore:
    """SQL-backed conversation history (replaces the per-session JSON dump).

    Backed by the relational ``turns`` table (``app.storage.history_store``).
    Keeps the ``load/save/append`` interface so the rest of the app and the
    existing unit tests are unchanged; the backend is SQLite by default and can
    be switched to MySQL via ``DATABASE_URL``.
    """

    def __init__(self, path: str | Path | None = None, db_path: str | Path | None = None):
        from ..storage.history_store import SQLChatStore
        self._store = SQLChatStore(path=path, db_path=db_path)

    def load(self, session_id: str) -> list[HistoryTurn]:
        return self._store.load(session_id)

    def save(self, session_id: str, turns: list[HistoryTurn]) -> list[HistoryTurn]:
        return self._store.save(session_id, turns)

    def append(self, session_id: str, turn: HistoryTurn) -> list[HistoryTurn]:
        return self._store.append(session_id, turn)


class HistoryManager:
    """Sliding-window + optional rolling summary over a session's history."""

    def __init__(
        self,
        store: ChatStore,
        session_id: str,
        max_turns: int = 8,
        summary_tokens: int = 300,
        summarizer: Optional[Callable[[list[HistoryTurn]], str]] = None,
    ):
        self.store = store
        self.session_id = session_id
        self.max_turns = max(1, int(max_turns))
        self.summary_tokens = int(summary_tokens)
        self.summarizer = summarizer

    def load(self) -> list[HistoryTurn]:
        return self.store.load(self.session_id)

    def append(self, turn: HistoryTurn) -> list[HistoryTurn]:
        return self.store.append(self.session_id, turn)

    def trim(self, turns: list[HistoryTurn]) -> tuple[str, list[HistoryTurn]]:
        """Return ``(summary_text, recent_turns)``.

        * ``recent_turns`` are the last ``max_turns`` in full (highest priority).
        * ``summary_text`` is a compressed recap of everything older, produced
          by the optional summarizer or, in the worst case, a fixed marker.
        """
        if len(turns) <= self.max_turns:
            return "", turns

        old = turns[: -self.max_turns]
        recent = turns[-self.max_turns:]
        if self.summarizer is not None:
            summary = self.summarizer(old)
            # keep the summary within its own token budget
            if token_len(summary) > self.summary_tokens:
                summary = summary[: int(self.summary_tokens * 3)]
        else:
            # Deterministic fallback: keep the last exchange as a terse recap.
            last = old[-1]
            summary = f"（早期对话）用户曾问：{last.user[:60]}；我答：{last.assistant[:60]}"
        return summary, recent

    def rolling_summary_all(self, turns: list[HistoryTurn]) -> str:
        """Collapse an entire session into one summary (for the context panel)."""
        if not turns:
            return ""
        if self.summarizer is not None:
            return self.summarizer(turns)
        return f"（共 {len(turns)} 轮历史）最后谈论：{turns[-1].user[:60]}"
