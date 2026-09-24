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
from ..storage.cache import get_cache

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
        self._emb_store = None
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

    def _search_uncached(self, query: str, k: int) -> list[RetrievedChunk]:
        if self.backend == "dashscope":
            vec = self._embed_search(query, k)
            if vec:
                return vec
        return self.bm25.search(query, k)

    def _embed_search(self, query: str, k: int) -> list[RetrievedChunk]:
        """FAISS / DashScope embedding similarity (requires key + deps)."""
        try:
            from langchain_community.vectorstores import FAISS
            from langchain_community.embeddings import DashScopeEmbeddings
        except Exception:
            return []
        try:
            emb = DashScopeEmbeddings(model=config.QWEN_EMBED_MODEL)
            store = FAISS.load_local(
                config.FAISS_PERSIST_DIR, emb, index_name="index",
                allow_dangerous_deserialization=True,
            )
            docs = store.similarity_search(query, k=k)
            return [
                RetrievedChunk(
                    text=d.page_content,
                    meta=dict(d.metadata or {}),
                    score=1.0,
                    source=str((d.metadata or {}).get("source", "")),
                )
                for d in docs
            ]
        except Exception:
            return []


def get_retriever() -> Retriever:
    return Retriever()
