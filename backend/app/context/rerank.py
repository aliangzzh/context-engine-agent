"""Retrieval results re-ranking and context priority scoring.

A real context engine does not blindly paste retrieval hits into the prompt: it
scores them and keeps the best. This module provides a dependency-free lexical
reranker (term/entity overlap) plus an optional cross-encoder path, and assigns
each surviving chunk a ``priority`` used by the TokenBudget.
"""
from __future__ import annotations

import re
from typing import Optional

from ..schemas import RetrievedChunk

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def lexical_overlap(query: str, text: str) -> float:
    """Jaccard-like overlap between the query and a candidate chunk."""
    q = tokenize(query)
    t = tokenize(text)
    if not q or not t:
        return 0.0
    return len(q & t) / max(1, len(q))


class Reranker:
    """Improve ordering of raw retrieval hits before they enter the context."""

    def __init__(self, cross_encoder: Optional[object] = None):
        self.cross_encoder = cross_encoder  # optional (sentence-transformers)

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        boost_overlap: float = 0.6,
    ) -> list[RetrievedChunk]:
        """Return chunks sorted best-first, each with a final score and priority."""
        if not chunks:
            return []

        scored: list[RetrievedChunk] = []
        for idx, c in enumerate(chunks):
            score = float(c.score or 0.0)
            if self.cross_encoder is not None:
                try:
                    score = float(self.cross_encoder.predict([(query, c.text)], ) [0])
                except Exception:
                    score = 0.0
            else:
                # blend the raw retriever score with lexical overlap
                score = score * (1 - boost_overlap) + lexical_overlap(query, c.text) * boost_overlap
            scored.append(c.model_copy(update={"score": round(score, 4)}))

        scored.sort(key=lambda c: c.score, reverse=True)
        # priority descends with rank (best chunk highest priority)
        max_score = scored[0].score if scored[0].score else 1.0
        for rank, c in enumerate(scored):
            rel = c.score / max_score if max_score else 0.0
            c = c.model_copy(update={"priority": int(10 + round(rel * 100))})
            scored[rank] = c
        return scored
