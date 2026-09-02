"""Token estimation and budget management for the Context Engine.

We ship a dependency-free heuristic so the engine runs offline, but upgrade to
``tiktoken`` when it is installed for more faithful counts.
"""
from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

try:  # optional precise tokenizer (OpenAI BPE); fall back to heuristic
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return len(_ENC.encode(text, disallowed_special=()))

except Exception:  # pragma: no cover - heuristic fallback
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        cjk = len(_CJK_RE.findall(text))
        other = len(text) - cjk
        # CJK chars are roughly 1 token on many Chinese-capable tokenizers;
        # ASCII text averages ~4 chars/token.
        return int(cjk * 1.0 + other / 4.0) + 1


def token_len(text: str) -> int:
    return estimate_tokens(text)


class TokenBudget:
    """Reserve a budget and let slots compete for it by priority.

    Trim order (lowest priority first) mirrors how real context engines behave:
    ancient chat history and low-scoring retrieval go before the system prompt
    and the current user turn.
    """

    def __init__(self, budget: int):
        self.budget = max(1, int(budget))

    def allocate(
        self,
        slots: list[dict],
        *,
        min_keep: int = 1,
    ) -> tuple[list[dict], int]:
        """Return the slots that fit the budget and the number of trimmed tokens.

        Each slot is a dict with keys ``kind``, ``content``, ``priority`` (int).
        The lowest-priority slots are trimmed first (repeatedly dropping the
        lowest-priority slot until the budget is met), while preserving at least
        ``min_keep`` slots so we never trim everything.
        """
        if not slots:
            return [], 0

        total = sum(token_len(s["content"]) for s in slots)
        if total <= self.budget:
            return slots, 0

        remaining = list(slots)
        while len(remaining) > min_keep:
            used = sum(token_len(s["content"]) for s in remaining)
            if used <= self.budget:
                break
            # drop the lowest-priority slot (stable tie-break by index)
            lowest = min(
                range(len(remaining)),
                key=lambda i: (remaining[i].get("priority", 0), i),
            )
            remaining.pop(lowest)

        kept_tokens = sum(token_len(s["content"]) for s in remaining)
        return remaining, total - kept_tokens
