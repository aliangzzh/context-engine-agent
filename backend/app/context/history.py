"""Conversation history with sliding-window and summary compression.

This is the piece the original RAG project was missing: instead of dumping the
entire JSON history back into every prompt (which grows until it blows the
context window), we keep only the most recent ``max_turns`` in full and
collapse everything older into a rolling summary.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..context.token_budget import token_len


@dataclass
class HistoryTurn:
    user: str
    assistant: str


class ChatStore:
    """A tiny JSON-per-session persistence layer (replaces the naive dump)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def _file(self, session_id: str) -> Path:
        # sanitize session id for filesystem safety
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.path / (safe or "default")

    def load(self, session_id: str) -> list[HistoryTurn]:
        f = self._file(session_id)
        if not f.exists():
            return []
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return []
        turns = []
        for item in raw:
            if isinstance(item, dict):
                turns.append(HistoryTurn(user=item.get("user", ""), assistant=item.get("assistant", "")))
        return turns

    def save(self, session_id: str, turns: list[HistoryTurn]) -> None:
        f = self._file(session_id)
        data = [{"user": t.user, "assistant": t.assistant} for t in turns]
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, f)

    def append(self, session_id: str, turn: HistoryTurn) -> list[HistoryTurn]:
        turns = self.load(session_id)
        turns.append(turn)
        self.save(session_id, turns)
        return turns


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
