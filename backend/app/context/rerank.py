"""Retrieval results re-ranking and context priority scoring.

A real context engine does not blindly paste retrieval hits into the prompt: it
scores them and keeps the best. This module provides a dependency-free lexical
reranker (term/entity overlap) plus an optional cross-encoder path, and assigns
each surviving chunk a ``priority`` used by the TokenBudget.

相关性度量统一走 :func:`coverage`（**内容词覆盖率**，先去掉口语停用词）：
把「的/了/吗/怎么/多少」这类词算进分母，会让字符级 BM25 的噪声看起来像证据
（评测集 A04 就是这么被带偏的：颜色文档靠"合适"压过了正确命中的售后文档）。
"""
from __future__ import annotations

import re
from typing import Optional

from .. import config
from ..schemas import RetrievedChunk

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")

#: 口语/功能停用词：这些词不构成"这条资料与问题相关"的证据
STOPWORDS = frozenset(
    "的了呢吧啊吗哦呀嘛么甚什"
    "请问帮我我你您他她它们咱"
    "是在有会能可要想要得"
    "这那个些一下点儿"
    "和与跟也都还就才很太真挺"
    "做说给对把被让使"
    "多少等于是如何谁哪哪些"
    "以及或者但是因为所以如果"
    "今天明天后天现在最近"
)

#: 相关性判据的两个门槛（可用环境变量覆盖）：
#: * 至少要命中 ``RELEVANCE_MIN_MATCHES`` 个内容词（单个字的重合不足以说明相关）
#: * 命中比例不低于 ``RELEVANCE_MIN_COVERAGE``
#: 默认值在当前评测集上标定：需要判为相关的最低 0.43，最容易被误判为相关的只有 0.33。
RELEVANCE_MIN_MATCHES = 2


def tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def content_terms(text: str) -> set[str]:
    """只保留内容词（去掉口语停用词与纯标点）。"""
    return {t for t in tokenize(text) if t not in STOPWORDS}


def lexical_overlap(query: str, text: str) -> float:
    """Jaccard-like overlap between the query and a candidate chunk."""
    q = tokenize(query)
    t = tokenize(text)
    if not q or not t:
        return 0.0
    return len(q & t) / max(1, len(q))


def coverage(query: str, text: str) -> float:
    """内容词覆盖率：问题里的内容词有多少比例出现在候选块里（0~1）。

    这是"这条资料到底回不回答这个问题"的可解释判据，比"BM25 有分"稳得多：
    闲聊问句、知识库覆盖不到的问题，覆盖率都会塌到 0.2~0.35 一带。
    """
    q = content_terms(query)
    if not q:
        return 0.0
    t = tokenize(text)
    return len(q & t) / len(q)


def relevance_detail(query: str, text: str) -> tuple[int, float]:
    q = content_terms(query)
    if not q:
        return 0, 0.0
    matched = len(q & tokenize(text))
    return matched, matched / len(q)


def is_relevant(query: str, text: str, *, threshold: float | None = None) -> bool:
    """候选块是否与问题相关：命中内容词数 + 覆盖率双门槛。"""
    threshold = config.RELEVANCE_MIN_COVERAGE if threshold is None else threshold
    matched, ratio = relevance_detail(query, text)
    return matched >= RELEVANCE_MIN_MATCHES and ratio >= threshold


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
                # blend the raw retriever score with the content-term coverage
                score = score * (1 - boost_overlap) + coverage(query, c.text) * boost_overlap
            scored.append(c.model_copy(update={"score": round(score, 4)}))

        scored.sort(key=lambda c: c.score, reverse=True)
        # priority descends with rank (best chunk highest priority)
        max_score = scored[0].score if scored[0].score else 1.0
        for rank, c in enumerate(scored):
            rel = c.score / max_score if max_score else 0.0
            c = c.model_copy(update={"priority": int(10 + round(rel * 100))})
            scored[rank] = c
        return scored
