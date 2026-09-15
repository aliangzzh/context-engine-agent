"""SQL 仓储：知识库分块（kb_chunks）与 badcase 反馈（feedback）。

数据库读写（MySQL）与列表分页：
这里的读都是真正的 SQL——``GROUP BY`` 聚合、``LIMIT/OFFSET`` 分页、
``LIKE`` 搜索、``DELETE`` 删除，不是把文件读进内存再切片。

两个仓储都遵守"连接在 A 线程建、B 线程用"的现实（HTTP 服务器是多线程的），
所以内部用 ``RLock`` 串行化，写操作走 ``db.transaction`` 保证原子性。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from .. import config
from ..decorators import cache_result
from ..errors import AppError, ErrorCode
from . import db

MAX_PAGE_SIZE = 100


def normalize_page(page: int, size: int) -> tuple[int, int, int]:
    """校验并归一化分页参数，返回 ``(page, size, offset)``。"""
    try:
        page = int(page)
        size = int(size)
    except (TypeError, ValueError):
        raise AppError(ErrorCode.VALIDATION_ERROR, "page/size 必须是整数")
    if page < 1:
        raise AppError(ErrorCode.VALIDATION_ERROR, "page 从 1 开始", detail={"page": page})
    if size < 1 or size > MAX_PAGE_SIZE:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"size 必须在 1~{MAX_PAGE_SIZE} 之间",
            detail={"size": size},
        )
    return page, size, (page - 1) * size


class _BaseRepo:
    def __init__(self, db_path: Optional[object] = None):
        self._lock = threading.RLock()
        if config.effective_db_backend() == "mysql":
            self._ph = "%s"
            self._conn = db.connect()
        else:
            self._ph = "?"
            path = Path(db_path) if db_path is not None else config.DB_PATH
            if path.is_dir():
                path = path / "app.db"
            self._conn = db.connect_sqlite(path)

    def _cursor(self):
        return self._conn.cursor()

    @staticmethod
    def _row_to_dict(row) -> dict:
        if hasattr(row, "keys"):
            return {k: row[k] for k in row.keys()}
        return dict(row)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


class KbRepository(_BaseRepo):
    """知识库分块的 SQL 读写（列表 / 分页 / 搜索 / 删除 / 统计）。"""

    def add_chunks(self, source: str, chunks: list[str], md5: str = "") -> int:
        if not chunks:
            return 0
        now = db.now()
        with self._lock, db.transaction(self._conn):
            cur = self._cursor()
            for text in chunks:
                cur.execute(
                    f"INSERT INTO kb_chunks (source, md5, text, created_at) "
                    f"VALUES ({self._ph},{self._ph},{self._ph},{self._ph})",
                    [source, md5, text, now],
                )
        return len(chunks)

    def has_md5(self, md5: str) -> bool:
        with self._lock:
            cur = self._cursor()
            cur.execute(f"SELECT 1 FROM kb_chunks WHERE md5={self._ph} LIMIT 1", [md5])
            return cur.fetchone() is not None

    def list_sources(self, page: int = 1, size: int = 10, q: str = "") -> dict:
        page, size, offset = normalize_page(page, size)
        q = (q or "").strip()
        where, args = "", []
        if q:
            where = f"WHERE source LIKE {self._ph}"
            args.append(f"%{q}%")
        with self._lock:
            cur = self._cursor()
            cur.execute(f"SELECT COUNT(DISTINCT source) AS n FROM kb_chunks {where}", args)
            total = int(self._row_to_dict(cur.fetchone())["n"])
            cur.execute(
                f"SELECT source, COUNT(*) AS chunks, MAX(created_at) AS created_at "
                f"FROM kb_chunks {where} GROUP BY source "
                f"ORDER BY created_at DESC, source ASC LIMIT {self._ph} OFFSET {self._ph}",
                args + [size, offset],
            )
            items = [self._row_to_dict(r) for r in cur.fetchall()]
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size,
        }

    def delete_source(self, source: str) -> int:
        if not source:
            raise AppError(ErrorCode.VALIDATION_ERROR, "source 不能为空")
        with self._lock, db.transaction(self._conn):
            cur = self._cursor()
            cur.execute(f"DELETE FROM kb_chunks WHERE source={self._ph}", [source])
            removed = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        return int(removed)

    def stats(self) -> dict:
        with self._lock:
            cur = self._cursor()
            cur.execute("SELECT COUNT(*) AS chunks, COUNT(DISTINCT source) AS sources FROM kb_chunks")
            row = self._row_to_dict(cur.fetchone())
        return {"chunks": int(row["chunks"] or 0), "sources": int(row["sources"] or 0)}

    @cache_result(ttl=30)
    def chunk_length_histogram(self) -> list[dict]:
        """分块长度分布（看板用）。聚合查询开销随数据量增长，缓存 30s。"""
        buckets = [(0, 100), (100, 200), (200, 300), (300, 500), (500, 10 ** 9)]
        with self._lock:
            cur = self._cursor()
            out = []
            for low, high in buckets:
                cur.execute(
                    f"SELECT COUNT(*) AS n FROM kb_chunks "
                    f"WHERE LENGTH(text) >= {self._ph} AND LENGTH(text) < {self._ph}",
                    [low, high],
                )
                label = f"{low}-{high}" if high < 10 ** 9 else f"{low}+"
                out.append({"bucket": label, "count": int(self._row_to_dict(cur.fetchone())["n"])})
        return out

    def all_chunks(self) -> list[dict]:
        with self._lock:
            cur = self._cursor()
            cur.execute("SELECT source, text, created_at FROM kb_chunks ORDER BY id")
            return [self._row_to_dict(r) for r in cur.fetchall()]

    def all_md5(self) -> set:
        with self._lock:
            cur = self._cursor()
            cur.execute("SELECT DISTINCT md5 FROM kb_chunks WHERE md5 <> ''")
            return {self._row_to_dict(r)["md5"] for r in cur.fetchall()}


class FeedbackRepository(_BaseRepo):
    """badcase 反馈的 SQL 读写（收集 → 列表 → 分布统计）。"""

    REASONS = ("answer_wrong", "hallucination", "missing_kb", "too_slow", "other")

    def add(self, session_id: str, message: str, answer: str, reason: str, note: str = "") -> dict:
        if reason not in self.REASONS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"reason 必须是 {list(self.REASONS)} 之一",
                detail={"reason": reason},
            )
        if not message.strip():
            raise AppError(ErrorCode.VALIDATION_ERROR, "message 不能为空")
        now = db.now()
        with self._lock, db.transaction(self._conn):
            cur = self._cursor()
            cur.execute(
                f"INSERT INTO feedback (session_id, message, answer, reason, note, created_at) "
                f"VALUES ({self._ph},{self._ph},{self._ph},{self._ph},{self._ph},{self._ph})",
                [session_id or "default", message, answer, reason, note, now],
            )
        return {"session_id": session_id or "default", "reason": reason, "created_at": now}

    def list(self, page: int = 1, size: int = 10) -> dict:
        page, size, offset = normalize_page(page, size)
        with self._lock:
            cur = self._cursor()
            cur.execute("SELECT COUNT(*) AS n FROM feedback")
            total = int(self._row_to_dict(cur.fetchone())["n"])
            cur.execute(
                f"SELECT id, session_id, message, answer, reason, note, created_at "
                f"FROM feedback ORDER BY id DESC LIMIT {self._ph} OFFSET {self._ph}",
                [size, offset],
            )
            items = [self._row_to_dict(r) for r in cur.fetchall()]
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size,
        }

    def distribution(self) -> list[dict]:
        """按原因聚合——看板页画 badcase 分布柱状图用。"""
        with self._lock:
            cur = self._cursor()
            cur.execute("SELECT reason, COUNT(*) AS n FROM feedback GROUP BY reason ORDER BY n DESC")
            rows = [self._row_to_dict(r) for r in cur.fetchall()]
        counts = {r["reason"]: int(r["n"]) for r in rows}
        return [{"reason": r, "count": counts.get(r, 0)} for r in self.REASONS]
