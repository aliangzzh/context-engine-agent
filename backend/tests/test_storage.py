"""Tests for the SQL storage layer + caching (offline SQLite / in-process LRU)."""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.context.history import ChatStore, HistoryManager, HistoryTurn
from app.storage.cache import LocalLRU
from app.storage.history_store import SQLChatStore

_SCRATCH = Path(__file__).parent / "_scratch"
_counter = {"n": 0}


def _scratch_dir() -> Path:
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    _counter["n"] += 1
    d = _SCRATCH / f"st_{os.getpid()}_{time.time_ns()}_{_counter['n']}"
    d.mkdir(parents=True, exist_ok=True)
    return d


class SQLChatStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch_dir()
        self.store = SQLChatStore(self.tmp / "hist")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_and_load(self):
        self.store.append("s1", HistoryTurn("你好", "你好，有什么可以帮你？"))
        self.store.append("s1", HistoryTurn("怎么洗", "水温不超过30度"))
        turns = self.store.load("s1")
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].user, "你好")
        self.assertEqual(turns[1].assistant, "水温不超过30度")

    def test_sessions_are_isolated(self):
        self.store.append("a", HistoryTurn("a-q", "a-a"))
        self.store.append("b", HistoryTurn("b-q", "b-a"))
        self.assertEqual(len(self.store.load("a")), 1)
        self.assertEqual(len(self.store.load("b")), 1)
        self.assertEqual(self.store.load("missing"), [])

    def test_save_replaces(self):
        self.store.append("s1", HistoryTurn("u1", "a1"))
        self.store.save("s1", [HistoryTurn("u2", "a2"), HistoryTurn("u3", "a3")])
        turns = self.store.load("s1")
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].user, "u2")

    def test_usable_from_other_threads(self):
        """回归测试：连接在 A 线程建、B 线程用必须不炸。

        标准库 ``ThreadingHTTPServer`` / FastAPI 的线程池都会让请求跑在
        连接创建线程之外；修复前这里直接抛
        ``sqlite3.ProgrammingError: SQLite objects created in a thread can only
        be used in that same thread``。
        """
        import threading

        errors: list[BaseException] = []

        def worker(i: int) -> None:
            try:
                self.store.append(f"t{i}", HistoryTurn(f"u{i}", f"a{i}"))
                self.assertEqual(len(self.store.load(f"t{i}")), 1)
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], f"跨线程访问存储报错：{errors[:1]}")
        self.assertEqual(sum(len(self.store.load(f"t{i}")) for i in range(8)), 8)


class ChatStoreWrapperTest(unittest.TestCase):
    def test_history_manager_works_over_sql(self):
        tmp = _scratch_dir()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        store = ChatStore(tmp / "hist")
        hm = HistoryManager(store, "s1", max_turns=3)
        hm.append(HistoryTurn("a", "b"))
        self.assertEqual(hm.load(), [HistoryTurn("a", "b")])
        summary, recent = hm.trim([HistoryTurn(f"u{i}", f"a{i}") for i in range(6)])
        self.assertEqual(len(recent), 3)
        self.assertTrue(summary)


class LocalLRUTest(unittest.TestCase):
    def test_get_set(self):
        c = LocalLRU(maxsize=4, ttl=60)
        c.set("k", {"x": 1})
        self.assertEqual(c.get("k"), {"x": 1})
        self.assertIsNone(c.get("missing"))

    def test_ttl_expires(self):
        c = LocalLRU(maxsize=4, ttl=0)
        c.set("k", "v")
        time.sleep(0.02)
        self.assertIsNone(c.get("k"))

    def test_eviction(self):
        c = LocalLRU(maxsize=2, ttl=60)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        self.assertIsNone(c.get("a"))  # oldest evicted
        self.assertEqual(c.get("b"), 2)
        self.assertEqual(c.get("c"), 3)

    def test_clear(self):
        c = LocalLRU(maxsize=4, ttl=60)
        c.set("k", "v")
        c.clear()
        self.assertIsNone(c.get("k"))


if __name__ == "__main__":
    unittest.main()
