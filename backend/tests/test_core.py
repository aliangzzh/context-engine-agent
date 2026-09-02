"""Stdlib unittest suite for the Context Engine / Multi-Agent backend.

Runs with no third-party test framework:
    python -m unittest tests.test_core -v        (from backend/)

Files are written to a workspace scratch dir (the system temp dir is read-only
under this sandbox), so tests use ``backend/tests/_scratch``.
"""
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.agents.orchestrator import AgentOrchestrator
from app.agents.router import route
from app.agents.tools import calculator, get_tool, get_weather
from app.context.engine import ContextEngine
from app.context.history import ChatStore, HistoryManager, HistoryTurn
from app.context.rerank import Reranker
from app.context.token_budget import TokenBudget, token_len
from app.models.fake import FakeModel
from app.retrieval.knowledge import KnowledgeBase
from app.retrieval.retriever import Retriever
from app.schemas import RetrievedChunk

_SCRATCH = Path(__file__).parent / "_scratch"
_counter = {"n": 0}


def _scratch_dir() -> Path:
    """Create a unique dir under the workspace scratch (tempfile.mkdtemp dirs
    are not writable under this sandbox, so we make one manually)."""
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    _counter["n"] += 1
    d = _SCRATCH / f"t{os.getpid()}_{int(time.time() * 1000)}_{_counter['n']}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rm(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class TokenBudgetTest(unittest.TestCase):
    def test_len_nonzero(self):
        self.assertGreater(token_len("加绒牛仔水温不超过30度"), 0)
        self.assertGreater(token_len("hello world"), 0)
        self.assertEqual(token_len(""), 0)

    def test_keeps_all_when_fits(self):
        b = TokenBudget(1000)
        slots = [{"kind": "a", "content": "x" * 20, "priority": 10}]
        kept, trimmed = b.allocate(slots)
        self.assertEqual(kept, slots)
        self.assertEqual(trimmed, 0)

    def test_trims_low_priority_first(self):
        # each of the three slots is ~26 tokens; budget 52 fits exactly two,
        # so the lowest-priority (history) slot must be trimmed.
        b = TokenBudget(52)
        slots = [
            {"kind": "system", "content": "S" * 100, "priority": 100},
            {"kind": "retrieval", "content": "R" * 100, "priority": 20},
            {"kind": "history", "content": "H" * 100, "priority": 5},
        ]
        kept, trimmed = b.allocate(slots, min_keep=1)
        kinds = [k["kind"] for k in kept]
        self.assertIn("system", kinds)
        self.assertNotIn("history", kinds)
        self.assertGreater(trimmed, 0)

    def test_never_trims_everything(self):
        b = TokenBudget(5)
        slots = [{"kind": "a", "content": "a" * 200, "priority": 1},
                 {"kind": "b", "content": "b" * 200, "priority": 2}]
        kept, _ = b.allocate(slots, min_keep=1)
        self.assertGreaterEqual(len(kept), 1)


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch_dir()
        self.store = ChatStore(self.tmp / "hist")

    def tearDown(self):
        _rm(self.tmp)

    def test_append_and_load(self):
        hm = HistoryManager(self.store, "s1", max_turns=3)
        hm.append(HistoryTurn("a", "b"))
        self.assertEqual(hm.load(), [HistoryTurn("a", "b")])

    def test_trim_keeps_recent(self):
        turns = [HistoryTurn(f"u{i}", f"a{i}") for i in range(10)]
        hm = HistoryManager(self.store, "s1", max_turns=3)
        summary, recent = hm.trim(turns)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1].user, "u9")
        self.assertTrue(summary)

    def test_trim_noop_when_short(self):
        turns = [HistoryTurn("u0", "a0"), HistoryTurn("u1", "a1")]
        hm = HistoryManager(self.store, "s1", max_turns=5)
        summary, recent = hm.trim(turns)
        self.assertEqual(summary, "")
        self.assertEqual(recent, turns)


class ContextEngineTest(unittest.TestCase):
    def _engine(self, budget=200):
        return ContextEngine(budget, reranker=Reranker())

    def test_build_creates_slots(self):
        ctx = self._engine(1000).build(
            user_input="加绒牛仔怎么洗",
            retrieved=[RetrievedChunk(text="加绒牛仔水温不超过30度", meta={"source": "a"}, score=1.0)],
            history=[HistoryTurn("尺码推荐", "身高170体重120斤建议L码")],
            system_prompt="你是知识问答助手",
        )
        kinds = {s.kind for s in ctx.slots}
        self.assertIn("system", kinds)
        self.assertIn("retrieval", kinds)
        self.assertIn("history", kinds)
        self.assertGreater(ctx.total_tokens, 0)

    def test_build_trims_over_budget(self):
        ctx = self._engine(60).build(
            user_input="问题",
            retrieved=[RetrievedChunk(text="长资料" * 30, meta={"source": "a"}, score=1.0)],
            history=[HistoryTurn("用户问题很长的历史", "很长的回答" * 5)],
            system_prompt="系统提示",
        )
        # low-priority content must have been trimmed away
        self.assertGreater(ctx.trimmed, 0)
        kinds = [s.kind for s in ctx.slots]
        self.assertIn("system", kinds)

    def test_render_messages_includes_user(self):
        engine = self._engine(1000)
        ctx = engine.build(
            user_input="如何洗涤", retrieved=[], history=[], system_prompt="系统提示"
        )
        msgs = engine.render_messages(ctx, "如何洗涤")
        self.assertEqual(msgs[-1], {"role": "user", "content": "如何洗涤"})
        self.assertEqual(msgs[0]["role"], "system")


class RetrieverTest(unittest.TestCase):
    def _mk(self):
        d = _scratch_dir()
        self.addCleanup(_rm, d)
        return Retriever(backend="bm25", kb_path=d / "kb.json")

    def test_bm25_search(self):
        r = self._mk()
        r.add_chunks(
            ["加绒牛仔水温不超过30度，中性洗涤剂", "纯棉保暖内衣禁止漂白", "身高170体重120斤建议L码"],
            [{"source": "a"}, {"source": "b"}, {"source": "c"}],
        )
        hits = r.search("加绒牛仔怎么洗")
        self.assertTrue(hits)
        self.assertIn("加绒牛仔", hits[0].text)
        self.assertEqual(hits[0].source, "a")

    def test_ingest_dedup(self):
        d = _scratch_dir()
        self.addCleanup(_rm, d)
        r = Retriever(backend="bm25", kb_path=d / "kb.json")
        kb = KnowledgeBase(r)
        self.assertEqual(kb.ingest_text("一些知识内容", "test.txt")["status"], "ingested")
        self.assertEqual(kb.ingest_text("一些知识内容", "test.txt")["status"], "skipped")
        self.assertEqual(len(r.texts), 1)


class ToolsTest(unittest.TestCase):
    def test_calculator(self):
        self.assertEqual(calculator("3*4+2"), "14")
        self.assertEqual(calculator("12*8"), "96")

    def test_calculator_invalid(self):
        self.assertIn("无法计算", calculator("abc"))

    def test_weather_offline_fallback(self):
        out = get_weather("上海")
        self.assertIsInstance(out, str)

    def test_tool_registry(self):
        self.assertIsNotNone(get_tool("get_weather"))
        self.assertIsNotNone(get_tool("calculator"))


class RouterTest(unittest.TestCase):
    def test_calc(self):
        self.assertIn("tool:calculator", route("计算 12*8"))

    def test_weather(self):
        self.assertIn("tool:get_weather", route("上海天气如何"))

    def test_kb(self):
        self.assertIn("retrieve", route("加绒牛仔怎么洗"))

    def test_greeting(self):
        self.assertIn("direct", route("你好"))


class OrchestratorTest(unittest.TestCase):
    def _build(self, kb_texts):
        d = _scratch_dir()
        self.addCleanup(_rm, d)
        r = Retriever(backend="bm25", kb_path=d / "kb.json")
        if kb_texts:
            r.add_chunks(kb_texts, [{"source": f"f{i}"} for i in range(len(kb_texts))])
        store = ChatStore(d / "hist")
        hm = HistoryManager(store, "s1", max_turns=4)
        eng = ContextEngine(1000, reranker=Reranker())
        return AgentOrchestrator(r, FakeModel(), hm, eng)

    def test_route_to_retrieve(self):
        orch = self._build(["加绒牛仔水温不超过30度"])
        res = orch.generate("加绒牛仔怎么洗", "s1")
        kinds = [s["kind"] for s in res.trace.to_list()]
        self.assertIn("router", kinds)
        self.assertIn("retrieve", kinds)
        self.assertNotEqual(res.answer, "")
        self.assertGreater(res.context.total_tokens, 0)

    def test_route_to_tool(self):
        orch = self._build([])
        res = orch.generate("计算 12*8", "s1")
        kinds = [s["kind"] for s in res.trace.to_list()]
        self.assertIn("tool", kinds)
        self.assertIn("96", res.answer)

    def test_router_present(self):
        orch = self._build([])
        res = orch.generate("你好", "s1")
        kinds = [s["kind"] for s in res.trace.to_list()]
        self.assertIn("router", kinds)


if __name__ == "__main__":
    unittest.main()
