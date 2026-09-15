"""Tests for the SQL storage layer + caching (offline SQLite / in-process LRU)."""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app.context.history import ChatStore, HistoryManager, HistoryTurn
from app.errors import AppError, ErrorCode
from app.storage.cache import LocalLRU
from app.storage.history_store import SQLChatStore
from app.storage.repo import FeedbackRepository, KbRepository, normalize_page

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


class TransactionTest(unittest.TestCase):
    """save() 是 DELETE + 多条 INSERT，必须整体成功或整体回滚。"""

    def setUp(self):
        self.tmp = _scratch_dir()
        self.store = SQLChatStore(self.tmp / "hist")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_rolls_back_on_failure(self):
        self.store.save("s1", [HistoryTurn("u1", "a1"), HistoryTurn("u2", "a2")])
        # 第二条是非法类型（sqlite 无法绑定）-> INSERT 抛错 -> 整个事务回滚
        bad = [HistoryTurn("u3", "a3"), HistoryTurn("u4", {"not": "a string"})]
        with self.assertRaises(Exception):
            self.store.save("s1", bad)
        turns = self.store.load("s1")
        self.assertEqual([t.user for t in turns], ["u1", "u2"],
                         "事务回滚后旧历史必须原样保留，不能被 DELETE 掉一半")

    def test_append_is_atomic(self):
        self.store.append("s1", HistoryTurn("u1", "a1"))
        with self.assertRaises(Exception):
            self.store.append("s1", HistoryTurn("u2", {"bad": True}))
        self.assertEqual(len(self.store.load("s1")), 1)


class KbRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch_dir()
        self.repo = KbRepository(db_path=self.tmp / "app.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_and_list_pagination(self):
        for i in range(7):
            self.repo.add_chunks(f"doc{i}.txt", [f"内容{i}-a", f"内容{i}-b"], md5=f"md5-{i}")
        page1 = self.repo.list_sources(page=1, size=3)
        self.assertEqual(page1["total"], 7)
        self.assertEqual(page1["pages"], 3)
        self.assertEqual(len(page1["items"]), 3)
        self.assertEqual(page1["items"][0]["chunks"], 2)
        page3 = self.repo.list_sources(page=3, size=3)
        self.assertEqual(len(page3["items"]), 1)

    def test_search_filters_by_source(self):
        self.repo.add_chunks("尺码推荐.txt", ["M码 L码"])
        self.repo.add_chunks("洗涤养护.txt", ["水温30度"])
        found = self.repo.list_sources(q="洗涤")
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["source"], "洗涤养护.txt")

    def test_dedup_and_delete(self):
        self.repo.add_chunks("a.txt", ["x"], md5="abc")
        self.assertTrue(self.repo.has_md5("abc"))
        self.assertIn("abc", self.repo.all_md5())
        removed = self.repo.delete_source("a.txt")
        self.assertEqual(removed, 1)
        self.assertEqual(self.repo.stats()["chunks"], 0)
        self.assertFalse(self.repo.has_md5("abc"))
        self.assertEqual(self.repo.delete_source("不存在的来源"), 0)

    def test_stats_and_histogram(self):
        self.repo.add_chunks("a.txt", ["短", "x" * 250])
        stats = self.repo.stats()
        self.assertEqual(stats["sources"], 1)
        self.assertEqual(stats["chunks"], 2)
        hist = {b["bucket"]: b["count"] for b in self.repo.chunk_length_histogram()}
        self.assertEqual(sum(hist.values()), 2)


class FeedbackRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch_dir()
        self.repo = FeedbackRepository(db_path=self.tmp / "app.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_list_and_distribution(self):
        self.repo.add("s1", "问题1", "回答1", "hallucination", "编造了参数")
        self.repo.add("s1", "问题2", "回答2", "missing_kb", "")
        self.repo.add("s2", "问题3", "回答3", "hallucination", "")
        listed = self.repo.list(page=1, size=2)
        self.assertEqual(listed["total"], 3)
        self.assertEqual(len(listed["items"]), 2)
        self.assertEqual(listed["items"][0]["message"], "问题3")  # 倒序
        dist = {d["reason"]: d["count"] for d in self.repo.distribution()}
        self.assertEqual(dist["hallucination"], 2)
        self.assertEqual(dist["missing_kb"], 1)
        self.assertEqual(dist["answer_wrong"], 0)

    def test_invalid_reason_rejected(self):
        with self.assertRaises(AppError) as ctx:
            self.repo.add("s1", "q", "a", "not-a-reason")
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION_ERROR)

    def test_empty_message_rejected(self):
        with self.assertRaises(AppError):
            self.repo.add("s1", "   ", "a", "other")


class PaginationTest(unittest.TestCase):
    def test_normalize_page(self):
        self.assertEqual(normalize_page(2, 10), (2, 10, 10))
        self.assertEqual(normalize_page("1", "5"), (1, 5, 0))

    def test_invalid_page_or_size(self):
        for page, size in ((0, 10), (-1, 10), (1, 0), (1, 101), ("x", 10)):
            with self.assertRaises(AppError) as ctx:
                normalize_page(page, size)
            self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION_ERROR)


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
