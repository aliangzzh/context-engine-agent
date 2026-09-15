"""Token estimation and budget management for the Context Engine.

We ship a dependency-free heuristic so the engine runs offline, but upgrade to
``tiktoken`` when it is installed for more faithful counts.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

#: Slot kinds that are never trimmed, however tight the budget gets.
#: ``system`` slots carry the instructions the whole answer depends on, and a
#: context can legitimately hold more than one of them (the system prompt plus,
#: say, an extra policy / tool-format slot). Protection is therefore decided by
#: *kind* — never by position or by how many slots happen to be left.
PROTECTED_KINDS: frozenset[str] = frozenset({"system"})

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
    and the current user turn. ``system`` slots are never trimmed at all.
    """

    def __init__(self, budget: int):
        self.budget = max(1, int(budget))

    def allocate(
        self,
        slots: list[dict],
        *,
        min_keep: int = 1,
        protect_kinds: Iterable[str] = PROTECTED_KINDS,
    ) -> tuple[list[dict], int]:
        """Return the slots that fit the budget and the number of trimmed tokens.

        Each slot is a dict with keys ``kind``, ``content``, ``priority`` (int).
        The lowest-priority slots are trimmed first (repeatedly dropping the
        lowest-priority *droppable* slot until the budget is met):

        * a slot whose ``kind`` is in ``protect_kinds`` (``system`` by default) is
          never dropped — *every* such slot, not just the first one;
        * at least ``min_keep`` slots are kept, so we never trim everything.

        If only protected slots are left and they still overflow, the loop stops
        and the overflow stays visible to the caller (``trimmed`` tokens plus the
        ``over_budget`` flag) instead of being silently swallowed.
        """
        if not slots:
            return [], 0

        total = sum(token_len(s["content"]) for s in slots)
        if total <= self.budget:
            return slots, 0

        protected = frozenset(protect_kinds)
        remaining = list(slots)
        while len(remaining) > min_keep:
            used = sum(token_len(s["content"]) for s in remaining)
            if used <= self.budget:
                break
            # lowest-priority droppable slot (stable tie-break by index);
            # protected kinds are skipped, so a second system slot survives too
            droppable = [
                i for i in range(len(remaining))
                if remaining[i].get("kind") not in protected
            ]
            if not droppable:
                break
            lowest = min(droppable, key=lambda i: (remaining[i].get("priority", 0), i))
            remaining.pop(lowest)

        kept_tokens = sum(token_len(s["content"]) for s in remaining)
        return remaining, total - kept_tokens
