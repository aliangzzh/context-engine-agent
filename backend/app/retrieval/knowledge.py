"""Knowledge ingestion: 文档解析 -> 切分 -> MD5 去重 -> 双写（检索索引 + SQL）。

文档解析切分与效果调优：
* 切分策略可切换（``CHUNK_STRATEGY=sentence|fixed``），便于做对比实验；
* 结构化数据（来源、分块数、时间）落到 ``kb_chunks`` 表，管理页的
  列表/分页/搜索/删除都走 SQL；
* 检索索引（BM25 / kb.json）与 SQL 在同一处更新，避免两边不一致。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from .. import config
from ..logging_config import get_logger, log, timed_block
from ..storage.repo import KbRepository
from .retriever import get_retriever

logger = get_logger("app.retrieval.knowledge")

#: 文档解析支持的纯文本类型
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".log"}

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _chunk_fixed(text: str, size: int, overlap: int) -> list[str]:
    """定长滑窗切分（baseline）。"""
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks, start, step = [], 0, max(1, size - overlap)
    while start < len(text):
        chunks.append(text[start:start + size])
        start += step
    return [c.strip() for c in chunks if c.strip()]


def _chunk_sentence(text: str, size: int, overlap: int) -> list[str]:
    """按句/段边界切分再打包（比定长切分少截断语义）。

    先按中英文句末标点与换行切开，再贪心地把整句塞进一个 chunk；单句就超过
    ``size`` 时退化为定长切。chunk 之间保留尾部 ``overlap`` 个字符做重叠，
    避免答案正好落在边界上被切掉。
    """
    sentences = [s for s in _SENT_SPLIT.split(text) if s and s.strip()]
    chunks: list[str] = []
    buf = ""
    for sent in sentences:
        if len(sent) > size:
            if buf.strip():
                chunks.append(buf.strip())
                buf = ""
            chunks.extend(_chunk_fixed(sent, size, overlap))
            continue
        if len(buf) + len(sent) <= size:
            buf += sent
        else:
            chunks.append(buf.strip())
            buf = (buf[-overlap:] if overlap > 0 else "") + sent
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c.strip()]


def _chunk(text: str, size: int | None = None, overlap: int | None = None,
           strategy: str | None = None) -> list[str]:
    size = size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    strategy = (strategy or config.CHUNK_STRATEGY).lower()
    if strategy == "fixed":
        return _chunk_fixed(text, size, overlap)
    return _chunk_sentence(text, size, overlap)


class KnowledgeBase:
    """知识入库 / 管理（检索索引 + SQL 元数据双写）。"""

    def __init__(self, retriever=None, repo: KbRepository | None = None):
        self.retriever = retriever or get_retriever()
        self.repo = repo or KbRepository()
        # 去重指纹：SQL（kb_chunks.md5）是权威，旧版 md5.txt 只做兼容读取
        self.md5_path = self.retriever.kb_path.parent / "md5.txt"

    # -- helpers ------------------------------------------------------------------
    def _legacy_md5s(self) -> set[str]:
        if not self.md5_path.exists():
            return set()
        try:
            return set(self.md5_path.read_text(encoding="utf-8").split())
        except Exception:
            return set()

    def _sync_md5_file(self) -> None:
        """把 SQL 里的指纹回写到 md5.txt（删除文档后尤其重要，否则会误判重复）。"""
        try:
            self.md5_path.parent.mkdir(parents=True, exist_ok=True)
            self.md5_path.write_text("\n".join(sorted(self.repo.all_md5())) + "\n", encoding="utf-8")
        except Exception:
            log(logger, 30, "md5_file_sync_failed")

    # -- ingest --------------------------------------------------------------------
    def ingest_text(self, text: str, source: str = "upload", *, md5: str | None = None) -> dict:
        md5 = md5 or _md5(text)
        if self.repo.has_md5(md5) or md5 in self._legacy_md5s():
            return {"status": "skipped", "chunks": 0, "filename": source, "reason": "dup-md5"}

        with timed_block(logger, "kb.chunk", chars=len(text), strategy=config.CHUNK_STRATEGY) as tb:
            chunks = _chunk(text)

        meta = {"source": source, "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self.retriever.add_chunks(chunks, [dict(meta) for _ in chunks])
        self.repo.add_chunks(source, chunks, md5)
        self._sync_md5_file()

        log(logger, 20, "kb.ingested", source=source, chunks=len(chunks),
            chars=len(text), chunk_ms=round(tb.ms, 1))
        return {"status": "ingested", "chunks": len(chunks), "filename": source}

    def ingest_file(self, path: Path, source: str = "") -> dict:
        path = Path(path)
        name = source or path.name
        suffix = path.suffix.lower()
        if suffix not in _TEXT_SUFFIXES:
            return {"status": "unsupported", "chunks": 0, "filename": name,
                    "reason": f"unsupported-suffix:{suffix or 'none'}"}
        try:
            if suffix == ".csv":
                import csv
                from io import StringIO
                raw = path.read_text(encoding="utf-8", errors="ignore")
                rows = list(csv.reader(StringIO(raw)))
                text = "\n".join(",".join(r) for r in rows if r)
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            log(logger, 40, "kb.parse_failed", source=name, error=exc.__class__.__name__)
            return {"status": "failed", "chunks": 0, "filename": name, "reason": "parse-error"}
        return self.ingest_text(text, name)

    def ingest_upload(self, filename: str, data: bytes) -> dict:
        """上传文件（bytes）入库：扩展名受支持 + 内容非空，才进解析。"""
        path = Path(filename or "upload")
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            return {"status": "unsupported", "chunks": 0, "filename": path.name,
                    "reason": f"unsupported-suffix:{path.suffix.lower() or 'none'}"}
        text = data.decode("utf-8-sig", errors="ignore")
        if not text.strip():
            return {"status": "failed", "chunks": 0, "filename": path.name, "reason": "empty-file"}
        return self.ingest_text(text, path.name, md5=_md5(text))

    # -- manage ---------------------------------------------------------------------
    def delete_source(self, source: str) -> dict:
        removed_rows = self.repo.delete_source(source)
        removed_chunks = self.retriever.remove_source(source)
        self._sync_md5_file()
        log(logger, 20, "kb.deleted", source=source, rows=removed_rows, chunks=removed_chunks)
        return {"source": source, "deleted_chunks": removed_chunks, "deleted_rows": removed_rows}

    def list_sources(self, page: int = 1, size: int = 10, q: str = "") -> dict:
        return self.repo.list_sources(page=page, size=size, q=q)

    def stats(self) -> dict:
        return self.repo.stats()
