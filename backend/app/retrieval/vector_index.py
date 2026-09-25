"""FAISS 向量索引：建 / 增量追加 / 落盘 / **指纹校验**。

## 为什么需要这个模块

`retriever` 原来只会 ``FAISS.load_local``（读索引），而整个仓库里**没有任何
"建索引"的代码**——所以 ``RETRIEVAL_BACKEND=dashscope`` 实际上永远降级到 BM25。
这个模块补上缺的那一环。

## 三条设计约束（都是踩过的坑换来的）

1. **索引与语料是两套存储，靠指纹保持一致。**
   ``index_meta.json`` 记录 ``corpus_md5`` / ``embedding_model`` / ``chunk_count``；
   检索前先校验：不一致就判定 ``STALE`` 并**降级 BM25**。
   不靠"记得重建"，靠机器检测——**宁可暂时慢，也不返回过期结果**。

2. **任何失败都不影响入库主流程。**
   所有写操作只返回 True/False，异常只进日志。写失败的后果是"指纹失配 →
   下次检索判定 STALE → 降级"，而不是把上传接口打挂。

3. **依赖缺失 / 索引不存在 → ``UNAVAILABLE``**，由调用方降级 BM25。

## 指纹为什么用"排序后拼接再 md5"

本地计算、零 API 成本，且与分块顺序无关（同一批内容换个顺序指纹相同）。
增删任何一个分块都会改变指纹——这正是我们要的。

## 手写索引（首次建索引 / 换 embedding 模型后重建）

    python -m app.retrieval.vector_index            # 从 kb.json 建索引
    python -m app.retrieval.vector_index --status   # 只看状态，不建
"""
from __future__ import annotations

import hashlib
import importlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config
from ..logging_config import get_logger, log
from ..schemas import RetrievedChunk

logger = get_logger("app.retrieval.vector")

META_NAME = "index_meta.json"


class VectorStatus:
    """索引可用性三态。

    区分 ``STALE`` 和 ``UNAVAILABLE`` 很重要：前者是"有索引但不新鲜"（多半是
    上传/删除后没同步成功），后者是"压根没有"（依赖缺失 / 从没建过）。
    两者的排障方向完全不同，所以日志和 /health 里要分开上报。
    """

    READY = "ready"            # 依赖齐 + 索引在 + 指纹匹配
    STALE = "stale"            # 索引在，但与当前语料/模型不一致
    UNAVAILABLE = "unavailable"  # 依赖缺失 / 索引或 meta 不存在 / 加载失败


def corpus_fingerprint(texts) -> str:
    """语料指纹：排序后逐条哈希。本地计算，不调 embedding，不花 API。"""
    h = hashlib.md5()
    for text in sorted(texts):
        h.update(text.encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()


def missing_deps() -> list[str]:
    """返回缺失的可选依赖名（用于 /health 与日志，解释"为什么降级"）。

    **必须直接探测底层 ``faiss``**：``langchain_community.vectorstores`` 是懒加载
    ``faiss`` 的——只导入包装类不会报错，会造成"检测说可用、一建索引就炸"的假阳性。
    """
    missing: list[str] = []
    for name in ("faiss", "langchain_community", "dashscope"):
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    return missing


def _deps():
    """返回 ``(FAISS, DashScopeEmbeddings)``；任一缺失都返回 ``(None, None)``。

    依赖是"可选"的（CI 只装 requirements.txt），所以这里必须能优雅失败。
    """
    if missing_deps():
        return None, None
    try:
        from langchain_community.embeddings import DashScopeEmbeddings
        from langchain_community.vectorstores import FAISS

        return FAISS, DashScopeEmbeddings
    except Exception:  # pragma: no cover - 取决于环境是否装了可选依赖
        return None, None


def deps_available() -> bool:
    return not missing_deps()


class VectorIndex:
    """一个目录 = 一份索引（``<name>.faiss`` + ``<name>.pkl`` + ``index_meta.json``）。"""

    def __init__(
        self,
        index_dir: Optional[str | Path] = None,
        index_name: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        self.dir = Path(index_dir or config.FAISS_PERSIST_DIR)
        self.name = index_name or config.VECTOR_INDEX_NAME
        self.embedding_model = embedding_model or config.QWEN_EMBED_MODEL
        # 已加载的 store 缓存：否则每次检索都要 FAISS.load_local（读盘 + 反序列化）
        self._store = None
        #: 最近一次失败的原因（只用于日志 / /health 展示，不参与判定）
        self.last_error = ""

    # -- meta ---------------------------------------------------------------------
    @property
    def meta_path(self) -> Path:
        return self.dir / META_NAME

    def read_meta(self) -> dict:
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_meta(self, texts) -> None:
        """索引写成功后更新指纹 —— 这一步决定了下一次检索是 READY 还是 STALE。"""
        payload = {
            "embedding_model": self.embedding_model,
            "index_name": self.name,
            "chunk_count": len(texts),
            "corpus_md5": corpus_fingerprint(texts),
            "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._store = None  # 索引变了，缓存作废

    def describe(self, texts=None) -> dict:
        """给人看的状态摘要（/health 用）。"""
        meta = self.read_meta()
        info = {
            "status": self.status(texts) if texts is not None else (
                VectorStatus.UNAVAILABLE if not meta else "unknown"
            ),
            "dir": str(self.dir),
            "index_name": self.name,
            "embedding_model": self.embedding_model,
            "chunk_count": meta.get("chunk_count"),
            "built_at": meta.get("built_at"),
        }
        if self.last_error:
            info["last_error"] = self.last_error
        return info

    # -- status -------------------------------------------------------------------
    def status(self, texts) -> str:
        """三态判定。**顺序由便宜到贵，快速失败。**

        1. 依赖能 import 吗          -> UNAVAILABLE
        2. index_meta.json 存在吗    -> UNAVAILABLE
        3. embedding 模型与配置一致吗 -> STALE（换模型必须重建）
        4. 语料指纹一致吗            -> STALE（增删过分块）
        5. 都不然                    -> READY
        """
        FAISS, _ = _deps()
        if FAISS is None:
            return VectorStatus.UNAVAILABLE
        meta = self.read_meta()
        if not meta:
            return VectorStatus.UNAVAILABLE
        if meta.get("embedding_model") != self.embedding_model:
            return VectorStatus.STALE
        if meta.get("corpus_md5") != corpus_fingerprint(texts):
            return VectorStatus.STALE
        return VectorStatus.READY

    # -- write --------------------------------------------------------------------
    def _load(self):
        """加载并缓存 store；失败返回 None（调用方据此判定不可用）。"""
        if self._store is not None:
            return self._store
        FAISS, Emb = _deps()
        if FAISS is None:
            return None
        try:
            store = FAISS.load_local(
                str(self.dir),
                Emb(model=self.embedding_model),
                index_name=self.name,
                allow_dangerous_deserialization=True,  # 加载 pickle 需显式授权
            )
        except Exception as exc:
            self.last_error = exc.__class__.__name__
            log(logger, 30, "vector.load_failed", error=self.last_error, dir=str(self.dir))
            return None
        self._store = store
        return store

    def rebuild(self, texts, metas) -> bool:
        """全量重建（首次建索引 / 删除文档后 / 换模型后）。失败返回 False。"""
        FAISS, Emb = _deps()
        if FAISS is None or not texts:
            return False
        try:
            emb = Emb(model=self.embedding_model)
            store = FAISS.from_texts(
                list(texts),
                embedding=emb,
                metadatas=[dict(m or {}) for m in metas],
            )
            self.dir.mkdir(parents=True, exist_ok=True)
            store.save_local(str(self.dir), index_name=self.name)
            self._write_meta(texts)
            log(logger, 20, "vector.rebuilt", chunks=len(texts), dir=str(self.dir))
            return True
        except Exception as exc:
            self.last_error = exc.__class__.__name__
            log(
                logger, 40, "vector.rebuild_failed",
                error=self.last_error, chunks=len(texts), msg=str(exc)[:200],
            )
            return False

    def add(self, chunks, metas, full_texts) -> bool:
        """增量追加到**已有**索引（只对新分块调 embedding）。

        失败返回 False —— 此时 meta 不更新，指纹自然失配，
        下一次检索会判定 STALE 并降级 BM25（不会返回过期结果）。
        """
        FAISS, Emb = _deps()
        if FAISS is None or not chunks:
            return False
        store = self._load()
        if store is None:
            return False
        try:
            store.add_texts(
                list(chunks),
                metadatas=[dict(m or {}) for m in metas],
            )
            store.save_local(str(self.dir), index_name=self.name)
            self._write_meta(full_texts)
            log(logger, 20, "vector.appended", added=len(chunks), total=len(full_texts))
            return True
        except Exception as exc:
            self.last_error = exc.__class__.__name__
            log(
                logger, 40, "vector.append_failed",
                error=self.last_error, added=len(chunks), msg=str(exc)[:200],
            )
            return False

    def add_or_rebuild(self, chunks, metas, full_texts, full_metas) -> bool:
        """有索引就增量追加，没有就全量重建。失败返回 False（见 add 的说明）。"""
        if not self.meta_path.exists():
            return self.rebuild(full_texts, full_metas)
        return self.add(chunks, metas, full_texts)

    def clear(self) -> None:
        """删除索引与 meta（回滚 / 强制重建用）。"""
        self._store = None
        for path in self.dir.glob(f"{self.name}.*"):
            try:
                path.unlink()
            except Exception:
                pass
        try:
            self.meta_path.unlink()
        except Exception:
            pass
        log(logger, 20, "vector.cleared", dir=str(self.dir))

    # -- read ---------------------------------------------------------------------
    def search(self, query: str, k: int) -> Optional[list[RetrievedChunk]]:
        """向量召回。

        返回值语义（调用方据此决定是否降级）::

            None  -> 不可用（依赖缺失 / 加载失败 / 检索异常）→ 调用方降级 BM25
            []    -> 可用，但没有命中
            [...] -> 命中，``score`` 是**真实相似度**（不是常量）
        """
        FAISS, _ = _deps()
        if FAISS is None:
            return None
        store = self._load()
        if store is None:
            return None
        try:
            pairs = store.similarity_search_with_score(query, k=k)
        except Exception as exc:
            self.last_error = exc.__class__.__name__
            log(logger, 40, "vector.search_failed", error=self.last_error)
            return None

        out: list[RetrievedChunk] = []
        for doc, distance in pairs:
            # FAISS 默认 IndexFlatL2：距离越小越相似。转成 (0,1] 的相似度，
            # 这样 rerank 里"原始分 × 权重"才有意义（旧版这里写死 1.0，
            # 结果两路分数量纲不可比，语义排序被词项重叠抹平）。
            sim = 1.0 / (1.0 + float(distance))
            meta = dict(getattr(doc, "metadata", None) or {})
            out.append(
                RetrievedChunk(
                    text=doc.page_content,
                    meta=meta,
                    score=round(sim, 4),
                    source=str(meta.get("source", "")),
                )
            )
        return out


# -- CLI：手动建索引 / 查状态 ---------------------------------------------------------
def _cli() -> int:
    import argparse

    from .retriever import get_retriever
    from .vector_index import VectorIndex as _VI  # 兼容 `python -m` 直接执行

    parser = argparse.ArgumentParser(description="构建/查看 FAISS 向量索引")
    parser.add_argument("--status", action="store_true", help="只看状态，不建索引")
    parser.add_argument("--force", action="store_true", help="无视依赖检查，强制重建")
    args = parser.parse_args()

    retriever = get_retriever()
    index = _VI()
    texts, metas = retriever.texts, retriever.metas

    print(f"语料: {len(texts)} 个分块    索引目录: {index.dir}")
    print(f"当前状态: {index.status(texts)}")
    if args.status:
        print(json.dumps(index.describe(texts), ensure_ascii=False, indent=2))
        return 0
    if not texts:
        print("语料为空，先上传知识库内容再建索引。")
        return 1
    if not deps_available() and not args.force:
        print("缺少可选依赖（faiss-cpu / langchain-community），无法建索引。")
        print("装依赖: pip install -r requirements-llm.txt")
        return 1
    ok = index.rebuild(texts, metas)
    print("重建完成" if ok else f"重建失败: {index.last_error}")
    print(json.dumps(index.describe(texts), ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
