"""Knowledge ingestion: chunking + MD5 dedup + write into the Retriever."""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from .. import config
from .retriever import get_retriever


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _chunk(text: str, size: int = None, overlap: int = None) -> list[str]:
    """Simple delimiter-aware chunker (no langchain dependency)."""
    size = size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks: list[str] = []
    start = 0
    step = size - overlap
    while start < len(text):
        end = min(start + size, len(text))
        # try to break on a sentence/clause boundary near the end
        seg = text[start:end]
        chunks.append(seg)
        start += step
    return [c.strip() for c in chunks if c.strip()]


class KnowledgeBase:
    def __init__(self, retriever=None):
        self.retriever = retriever or get_retriever()
        # scope dedup fingerprints to this particular KB (next to its index file)
        self.md5_path = self.retriever.kb_path.parent / "md5.txt"

    def ingest_text(self, text: str, source: str) -> dict:
        md5 = _md5(text)
        # dedup against already-stored md5 fingerprints
        fp = self.md5_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        if fp.exists() and md5 in fp.read_text(encoding="utf-8").split():
            return {"status": "skipped", "chunks": 0, "filename": source, "reason": "dup-md5"}

        chunks = _chunk(text)
        meta = {
            "source": source,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.retriever.add_chunks(chunks, [meta for _ in chunks])

        with open(fp, "a", encoding="utf-8") as f:
            f.write(md5 + "\n")
        return {"status": "ingested", "chunks": len(chunks), "filename": source}

    def ingest_file(self, path: Path, source: str = "") -> dict:
        path = Path(path)
        if path.suffix.lower() in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
        elif path.suffix.lower() == ".csv":
            import csv
            from io import StringIO
            rows = list(csv.reader(StringIO(path.read_text(encoding="utf-8", errors="ignore"))))
            text = "\n".join(",".join(r) for r in rows if r)
        elif path.suffix.lower() == ".json":
            text = path.read_text(encoding="utf-8", errors="ignore")
        else:
            return {"status": "unsupported", "chunks": 0, "filename": source or path.name}
        return self.ingest_text(text, source or path.name)
