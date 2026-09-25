"""Retrieval backend.

Default is a dependency-free BM25 index (offline, always works). When
``DASHSCOPE_API_KEY`` is present you can opt into embedding-similarity retrieval
with FAISS via ``RETRIEVAL_BACKEND=dashscope`` (or leave ``auto``).

Both expose the same ``search(query, k) -> list[RetrievedChunk]`` interface so
the Context Engine does not care which one is active.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from ..schemas import RetrievedChunk
from .. import config
from ..logging_config import get_logger, log
from ..storage.cache import get_cache
from .vector_index import VectorIndex, VectorStatus

logger = get_logger("app.retrieval")

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")

#: 领域同义词扩展（查询侧）。
#: 来自评测集失败分析：A04「买回来不合适能退吗？」在字符级 BM25 下，
#: 「合适」这类高频组合词给出的证据比「退」还强，导致售后政策掉到第 2 名。
#: 中文换货/退换是同一意图，把「退」扩成「退+换」，售后政策文档（含"退换"）得分
#: 就能超过颜色文档（含"合适"）。索引与查询共用 _TOKEN_RE，所以扩展只能加字，不能加词。
_QUERY_EXPAND: dict[str, tuple[str, ...]] = {
    "退": ("换",),
}


def _expand_query(tokens: set[str]) -> set[str]:
    out = set(tokens)
    for term, extra in _QUERY_EXPAND.items():
        if term in tokens:
            out.update(extra)
    return out


def _tok(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class BM25Index:
    """Minimal BM25 over an in-memory corpus (pure stdlib, no numpy)."""

    def __init__(self):
        self.docs: list[str] = []
        self.metas: list[dict] = []
        self._doc_tokens: list[set[str]] = []
        self._doc_tf: list[Counter] = []
        self._df: Counter = Counter()
        self._avgdl = 0.0
        self.k1 = 1.5
        self.b = 0.75
        self._n = 0

    def add_documents(self, texts: list[str], metas: Optional[list[dict]] = None) -> None:
        metas = metas or [{} for _ in texts]
        for text, meta in zip(texts, metas):
            self.docs.append(text)
            self.metas.append(meta)
            toks = _tok(text)
            tf = Counter(toks)
            self._doc_tokens.append(toks)
            self._doc_tf.append(tf)
            for t in toks:
                self._df[t] += 1
            self._n += 1
            self._avgdl += max(1, len(toks))
        if self._n:
            self._avgdl /= self._n

    def _idf(self, term: str) -> float:
        n = self._df.get(term, 0)
        # smoothed idf
        return math.log(1 + (self._n - n + 0.5) / (n + 0.5))

    def _score(self, query_toks: set[str], i: int) -> float:
        tf = self._doc_tf[i]
        dl = max(1, len(self._doc_tokens[i]))
        score = 0.0
        for term in query_toks:
            if term not in tf:
                continue
            f = tf[term]
            idf = self._idf(term)
            denom = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
            score += idf * (f * (self.k1 + 1)) / denom
        return score

    def search(self, query: str, k: int = 3) -> list[RetrievedChunk]:
        q = _expand_query(_tok(query))
        if not q or self._n == 0:
            return []
        scored = [(self._score(q, i), i) for i in range(self._n)]
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, i in scored[:k]:
            if score <= 0:
                continue
            out.append(
                RetrievedChunk(
                    text=self.docs[i],
                    meta=self.metas[i],
                    score=round(score, 4),
                    source=str(self.metas[i].get("source", "")),
                )
            )
        return out


class Retriever:
    """A pluggable facade over BM25 or embedding-similarity retrieval."""

    def __init__(self, backend: Optional[str] = None, kb_path: Optional[object] = None):
        self.backend = (backend or config.effective_retrieval_backend())
        self.kb_path = kb_path or (config.KB_DIR / "kb.json")
        self.texts: list[str] = []
        self.metas: list[dict] = []
        self.bm25 = BM25Index()
        #: 向量索引：建/追加/落盘/指纹校验都在它内部，这里只做调度与降级判定
        self.vector = VectorIndex()
        #: 最近一次降级原因（/health 与日志用；"没降级"时为空串）
        self.last_degrade = ""
        self._cache = get_cache()  # cache retrieval results (LRU by default)
        self.load()

    # -- storage -----------------------------------------------------------------
    def load(self) -> None:
        import json
        if self.kb_path.exists():
            try:
                data = json.loads(self.kb_path.read_text(encoding="utf-8"))
                self.texts = [c["text"] for c in data["chunks"]]
                self.metas = [c["meta"] for c in data["chunks"]]
            except Exception:
                self.texts, self.metas = [], []
        else:
            self.texts, self.metas = [], []
        self.bm25 = BM25Index()
        if self.texts:
            self.bm25.add_documents(self.texts, self.metas)

    def _persist(self) -> None:
        import json
        self.kb_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"chunks": [{"text": t, "meta": m} for t, m in zip(self.texts, self.metas)]}
        self.kb_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_chunks(self, texts: list[str], metas: list[dict]) -> None:
        self.texts.extend(texts)
        self.metas.extend(metas)
        self.bm25.add_documents(texts, metas)
        self._persist()
        # the underlying corpus changed -> previously cached results are stale
        self._cache.clear()

    def replace_all(self, texts: list[str], metas: list[dict]) -> None:
        """整体替换语料（删除文档后重建索引用）。"""
        self.texts = list(texts)
        self.metas = list(metas)
        self.bm25 = BM25Index()
        if self.texts:
            self.bm25.add_documents(self.texts, self.metas)
        self._persist()
        self._cache.clear()

    def remove_source(self, source: str) -> int:
        """删除某个来源的全部 chunk，返回删除条数（索引 + 落盘一起更新）。"""
        if not source:
            return 0
        keep_texts, keep_metas = [], []
        for text, meta in zip(self.texts, self.metas):
            if (meta or {}).get("source") == source:
                continue
            keep_texts.append(text)
            keep_metas.append(meta)
        removed = len(self.texts) - len(keep_texts)
        if removed:
            self.replace_all(keep_texts, keep_metas)
        return removed

    # -- search ---------------------------------------------------------------------
    def search(self, query: str, k: Optional[int] = None) -> list[RetrievedChunk]:
        k = k or config.TOP_K
        # Cache key includes backend + k so switching retrieval/flags is safe.
        key = f"retrieve:{self.backend}:{k}:{query}"
        cached = self._cache.get(key)
        if cached is not None:
            try:
                return [RetrievedChunk(**d) for d in cached]
            except Exception:
                pass  # bad cache payload -> recompute below
        result = self._search_uncached(query, k)
        # Store as JSON-safe dicts so both the LRU and Redis backends work.
        self._cache.set(key, [c.model_dump() for c in result])
        return result

    # -- 向量索引调度 ---------------------------------------------------------------
    def vector_status(self) -> str:
        """索引相对当前语料的三态：READY / STALE / UNAVAILABLE。"""
        return self.vector.status(self.texts)

    def effective_backend(self) -> str:
        """**运行时实际生效**的后端（含降级判定）。

        与 ``config.effective_retrieval_backend()``（配置层意愿）区分开：
        配置写着 dashscope、但索引过期或依赖缺失时，这里返回 ``bm25``。
        /health 的 ``retrieval_effective`` 字段用的就是它——避免"徽章说向量、
        实际跑 BM25"的误导。
        """
        if self.backend not in ("dashscope", "hybrid"):
            return "bm25"
        if self.vector_status() != VectorStatus.READY:
            return "bm25"
        return "bm25 + dashscope" if self.backend == "hybrid" else "dashscope"

    def _note_degrade(self, reason: str) -> None:
        """记录一次降级。reason 直接进日志和 /health，便于排障。"""
        self.last_degrade = reason
        log(logger, 30, "retrieval.degraded", reason=reason, configured=self.backend)

    def sync_vector_index(self, chunks: list[str], metas: list[dict]) -> bool:
        """入库后把新分块同步进索引。失败只返回 False（调用方记日志即可）。

        没启用向量后端时直接返回 False —— 不做无谓的 embedding 调用（那是要花钱的）。
        """
        if self.backend not in ("dashscope", "hybrid"):
            return False
        return self.vector.add_or_rebuild(chunks, metas, self.texts, self.metas)

    def rebuild_vector_index(self) -> bool:
        """全量重建索引（删除文档后 / 手动重建 / 换 embedding 模型后）。"""
        if self.backend not in ("dashscope", "hybrid"):
            return False
        return self.vector.rebuild(self.texts, self.metas)

    # -- dispatch ------------------------------------------------------------------
    def _search_uncached(self, query: str, k: int) -> list[RetrievedChunk]:
        """检索分发。**BM25 是地板，不是备胎**：任何异常路径都落到它。

        向量那路的返回值有三态语义（见 ``VectorIndex.search``）：
        ``None`` 不可用 / ``[]`` 可用但无命中 / ``[...]`` 命中。
        """
        if self.backend in ("dashscope", "hybrid"):
            status = self.vector_status()
            if status == VectorStatus.READY:
                vec = self.vector.search(query, k)
                if vec is None:
                    self._note_degrade("vector_error")
                elif self.backend == "hybrid":
                    # 两路都查，按名次融合（RRF 规避两路分数量纲不可比）
                    return _rrf_fuse(self.bm25.search(query, k), vec, k)
                elif vec:
                    return vec
                else:
                    self._note_degrade("vector_no_hit")
            else:
                self._note_degrade(status)  # stale / unavailable
        return self.bm25.search(query, k)


def _rrf_fuse(
    lexical: list[RetrievedChunk],
    vector: list[RetrievedChunk],
    k: int,
    *,
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion：按**名次**融合两路召回结果。

    为什么不用分数加权：BM25 的分数无界，向量那路是 (0,1] 的相似度，两者量纲
    不可比（归一化怎么做都是拍脑袋）。RRF 只看名次 —— ``1/(rrf_k + rank)``，
    天然绕开这个问题。``rrf_k=60`` 是原论文与 Elasticsearch 都在用的常用值。

    去重键用 ``(source, text[:80])``：同一段资料可能被两路同时召回，
    这时它的 RRF 分数会叠加（两路都排得前 → 更靠前），这正是融合的意图。
    """
    scores: dict[tuple, float] = {}
    by_key: dict[tuple, RetrievedChunk] = {}
    for results in (lexical, vector):
        for rank, chunk in enumerate(results):
            key = (chunk.source, chunk.text[:80])
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            by_key.setdefault(key, chunk)
    ordered = sorted(scores, key=lambda key: scores[key], reverse=True)[:k]
    return [
        by_key[key].model_copy(update={"score": round(scores[key], 6)})
        for key in ordered
    ]


def get_retriever() -> Retriever:
    return Retriever()
