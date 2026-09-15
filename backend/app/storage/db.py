"""Relational database connection + schema (stdlib sqlite3 by default).

The rest of the app is written against a small DBAPI-style interface so the
backend can be swapped by configuration:

* ``DATABASE_URL`` empty            -> local SQLite file (offline, zero deps).
* ``DATABASE_URL=mysql+pymysql://..``-> MySQL (needs ``pip install pymysql``).

The SQL is kept deliberately plain (CREATE TABLE / INSERT / SELECT / DELETE) so
it's readable as a real, hand-written persistence layer.
"""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

from .. import config

# --- schema ---------------------------------------------------------------------
# Normalized tables:
#   turns      : one row per user/assistant exchange (conversation history)
#   kb_chunks  : one row per knowledge chunk + md5 fingerprint (for dedup)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    user_text      TEXT    NOT NULL,
    assistant_text TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT    NOT NULL,
    md5        TEXT    NOT NULL,
    text       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_md5    ON kb_chunks(md5);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_source ON kb_chunks(source);

CREATE TABLE IF NOT EXISTS feedback (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    message        TEXT    NOT NULL,
    answer         TEXT    NOT NULL,
    reason         TEXT    NOT NULL,
    note           TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_reason ON feedback(reason);
"""


def _sqlite_path() -> Path:
    """Resolve the SQLite file path from DATABASE_URL (sqlite:///...) or default."""
    url = config.DATABASE_URL
    if url.lower().startswith("sqlite"):
        # strip prefix like sqlite:///path
        return Path(url.split("sqlite:///", 1)[-1])
    return config.DB_PATH


def connect() -> object:
    """Open a connection from config. sqlite3 by default; MySQL when configured."""
    if config.effective_db_backend() == "mysql":
        return _connect_mysql()
    return _connect_sqlite(_sqlite_path())


def _connect_sqlite(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # ``check_same_thread=False``: the app hands one store to a threaded HTTP
    # server (stdlib ThreadingHTTPServer / FastAPI's threadpool), so the
    # connection outlives the thread that created it. Concurrent use is
    # serialized by ``SQLChatStore._lock``.
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL improves read/write concurrency (a single web process reads & writes).
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    _init(conn)
    return conn


def _connect_mysql():
    # Requires `pip install pymysql`.
    import pymysql  # noqa: F401  (import raises a clear error if missing)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(config.DATABASE_URL.replace("mysql+pymysql", "mysql"))
        conn = pymysql.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=parsed.username or "",
            password=parsed.password or "",
            database=(parsed.path or "/").lstrip("/"),
            charset="utf8mb4",
        )
        _init_mysql(conn)
        return conn
    except ImportError:
        raise RuntimeError(
            "DATABASE_URL set to MySQL but pymysql is not installed. "
            "Run `pip install pymysql` or unset DATABASE_URL to use SQLite."
        )


def _init(conn) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def connect_sqlite(db_path) -> object:
    """Open (and initialize) a SQLite connection at an explicit path."""
    return _connect_sqlite(Path(db_path))


def _init_mysql(conn) -> None:
    """MySQL variant (AUTO_INCREMENT, no sqlite-only syntax)."""
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS turns ("
        " id BIGINT AUTO_INCREMENT PRIMARY KEY,"
        " session_id VARCHAR(128) NOT NULL,"
        " user_text TEXT NOT NULL, assistant_text TEXT NOT NULL,"
        " created_at VARCHAR(32) NOT NULL,"
        " INDEX idx_turns_session (session_id, id)"
        ")"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS kb_chunks ("
        " id BIGINT AUTO_INCREMENT PRIMARY KEY,"
        " source VARCHAR(255) NOT NULL, md5 VARCHAR(64) NOT NULL,"
        " `text` TEXT NOT NULL, created_at VARCHAR(32) NOT NULL,"
        " INDEX idx_kb_chunks_md5 (md5), INDEX idx_kb_chunks_source (source)"
        ")"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS feedback ("
        " id BIGINT AUTO_INCREMENT PRIMARY KEY,"
        " session_id VARCHAR(128) NOT NULL, message TEXT NOT NULL,"
        " answer TEXT NOT NULL, reason VARCHAR(64) NOT NULL,"
        " note TEXT NOT NULL, created_at VARCHAR(32) NOT NULL,"
        " INDEX idx_feedback_reason (reason)"
        ")"
    )
    conn.commit()


@contextlib.contextmanager
def transaction(conn):
    """显式事务：正常提交，异常回滚后原样抛出。

    用于"一组写操作要么全成功、要么全回滚"的场景——例如把一轮对话整体写回
    ``turns`` 表（先 DELETE 旧轮次再逐条 INSERT，中途失败必须回滚，否则历史
    会被删掉一半）。
    """
    try:
        yield conn
    except BaseException:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover - 回滚失败只能记录
            pass
        raise
    else:
        conn.commit()



def now() -> str:
    """ISO timestamp string used for created_at columns."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
