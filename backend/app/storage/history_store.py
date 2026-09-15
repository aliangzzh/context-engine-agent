"""SQL-backed conversation history store.

This replaces the per-session JSON file dump with a relational ``turns`` table,
so history is a real database read/write (CREATE TABLE / INSERT / SELECT / DELETE)
and the backend can be switched to MySQL via ``DATABASE_URL``.

The public interface is intentionally the same as the old JSON ``ChatStore``
(``load`` / ``save`` / ``append``) so the rest of the app is untouched.
"""
from __future__ import annotations

import threading
from pathlib import Path

from .. import config
from . import db


class SQLChatStore:
    def __init__(self, path=None, db_path=None):
        # Lazy import to avoid a circular import (storage <- context.history).
        from ..context.history import HistoryTurn  # noqa: F401
        self._history_turn = HistoryTurn
        # One store instance is shared by all request threads, and neither a
        # sqlite3 connection nor a pymysql connection is safe to use from two
        # threads at once -> serialize access.
        self._lock = threading.RLock()

        if config.effective_db_backend() == "mysql":
            self._ph = "%s"
            self._conn = db.connect()                     # dialect: MySQL
        else:
            self._ph = "?"
            if db_path is not None:
                sqlite_file = Path(db_path)
            elif path is not None:
                sqlite_file = Path(path) / "history.db"
            else:
                sqlite_file = config.DATA_DIR / "chat_history" / "history.db"
            self._conn = db.connect_sqlite(sqlite_file)   # dialect: SQLite

    # -- low-level helpers --------------------------------------------------------
    def _mk_turn(self, row):
        """Build a HistoryTurn from a row (dict-like for sqlite Row / dict cursor)."""
        if hasattr(row, "keys"):
            user = row["user_text"]
            assistant = row["assistant_text"]
        else:
            user, assistant = row[0], row[1]
        return self._history_turn(user=user, assistant=assistant)

    def _cursor(self):
        return self._conn.cursor()

    # -- public interface (same as the old JSON ChatStore) --------------------------
    def load(self, session_id: str) -> list:
        with self._lock:
            cur = self._cursor()
            cur.execute(
                f"SELECT user_text, assistant_text FROM turns "
                f"WHERE session_id={self._ph} ORDER BY id",
                [session_id],
            )
            return [self._mk_turn(r) for r in cur.fetchall()]

    def save(self, session_id: str, turns: list) -> list:
        # 先 DELETE 再逐条 INSERT：必须是一个事务，否则中途失败会把历史删掉一半。
        with self._lock, db.transaction(self._conn):
            cur = self._cursor()
            cur.execute(f"DELETE FROM turns WHERE session_id={self._ph}", [session_id])
            for t in turns:
                cur.execute(
                    f"INSERT INTO turns (session_id, user_text, assistant_text, created_at) "
                    f"VALUES ({self._ph},{self._ph},{self._ph},{self._ph})",
                    [session_id, t.user, t.assistant, db.now()],
                )
            return turns

    def append(self, session_id: str, turn) -> list:
        with self._lock, db.transaction(self._conn):
            cur = self._cursor()
            cur.execute(
                f"INSERT INTO turns (session_id, user_text, assistant_text, created_at) "
                f"VALUES ({self._ph},{self._ph},{self._ph},{self._ph})",
                [session_id, turn.user, turn.assistant, db.now()],
            )
        return self.load(session_id)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
