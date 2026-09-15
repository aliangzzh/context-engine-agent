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

from app import config
from app.agents.orchestrator import AgentOrchestrator
from app.agents.router import route
from app.agents.tools import calculator, get_tool, get_weather
from app.context.engine import ContextEngine
from app.context.history import ChatStore, HistoryManager, HistoryTurn
from app.context.rerank import Reranker
from app.context.summarizer import HistorySummarizer
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

    def test_second_system_slot_is_protected(self):
        """按 kind 保护：**两条** system slot 都必须留下，而不是只保第一条。

        旧的保护只有一个数量兜底（min_keep），一旦出现第二条 system slot，它就会
        被当成普通 slot 按优先级裁掉；现在保护按 kind 判定，与 slot 数量/顺序无关。
        """
        b = TokenBudget(5)
        slots = [
            {"kind": "system", "content": "S" * 100, "priority": 100},
            {"kind": "system", "content": "T" * 100, "priority": 90},
            {"kind": "retrieval", "content": "R" * 100, "priority": 20},
            {"kind": "history", "content": "H" * 100, "priority": 5},
        ]
        kept, trimmed = b.allocate(slots, min_keep=1)
        kinds = [k["kind"] for k in kept]
        self.assertEqual(kinds.count("system"), 2)       # 第二条 system 也没被裁
        self.assertEqual(kinds, ["system", "system"])    # 可裁的都被裁掉了
        self.assertGreater(trimmed, 0)


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

    def test_over_budget_is_reported(self):
        """超预算且已无可裁（只剩受保护的 system slot）时，必须如实上报 over_budget。

        曾经的静默缺陷：裁剪被 min_keep 数量兜底卡死，total 超出 budget 却没有任何
        提示 —— over_budget 就是让这个事实变得可见。现在 system 按 kind 保护、
        其余 slot 都能裁，「一条都没裁」只剩「system 提示本身就超预算」这一种情况，
        它依然必须如实上报。
        """
        ctx = self._engine(1).build(
            user_input="x",
            retrieved=[],                                      # 没有可裁的 slot
            history=[],
            system_prompt="you are a helper",
        )
        self.assertGreater(ctx.total_tokens, ctx.budget)   # 确实超了
        self.assertEqual(ctx.trimmed, 0)                   # 但一条都没裁
        self.assertTrue(ctx.over_budget)                   # ← 必须如实上报

    def test_trims_down_to_the_system_slot(self):
        """旧的「只剩 2 个 slot 时裁剪彻底失效」已修：2 个 slot 也要真的裁。

        min_keep=2 且只有 system/retrieval 两条时，循环条件直接不成立，明明可裁的
        retrieval 却一条都裁不掉（预算被静默突破）。改成「按 kind 保护 system +
        min_keep=1」后，retrieval 必须被裁掉，上下文里只剩 system。
        """
        ctx = self._engine(1).build(
            user_input="x",
            retrieved=[RetrievedChunk(text="hello world", score=1.0, source="a")],
            history=[],
            system_prompt="you are a helper",
        )
        self.assertEqual([s.kind for s in ctx.slots], ["system"])
        self.assertGreater(ctx.trimmed, 0)

    def test_not_over_budget(self):
        """没超预算时 over_budget 必须是 False（避免误报）。"""
        ctx = self._engine(4096).build(
            user_input="x", retrieved=[], history=[], system_prompt="sys"
        )
        self.assertFalse(ctx.over_budget)


class SummarizerTest(unittest.TestCase):
    """摘要器：是否真被调用、失败兜底、以及摘要槽在上下文里的位置。"""

    class _SpyModel:
        """假模型：只记录"被喂了什么"，用来验证调用链。"""

        name = "spy"

        def __init__(self):
            self.calls = []

        def generate(self, messages):
            self.calls.append(messages)
            return "SUMMARY-OK"

        def stream(self, messages):
            return iter([])

    class _BrokenModel:
        name = "broken"

        def generate(self, messages):
            raise RuntimeError("model down")

        def stream(self, messages):
            return iter([])

    def test_summarizer_calls_the_model(self):
        """摘要器必须真的调用模型，并按 system + user 两条消息的格式传参。"""
        spy = self._SpyModel()
        out = HistorySummarizer(spy).summarize_history(
            [HistoryTurn("q1", "a1"), HistoryTurn("q2", "a2")]
        )
        self.assertEqual(out, "SUMMARY-OK")
        self.assertEqual(len(spy.calls), 1)
        messages = spy.calls[0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("q1", messages[1]["content"])   # 旧轮次确实被喂进去了

    def test_summarizer_falls_back_when_model_fails(self):
        """模型失败时必须降级到规则模板，而不是抛异常或返回空。"""
        out = HistorySummarizer(self._BrokenModel()).summarize_history(
            [HistoryTurn("q1", "a1")]
        )
        self.assertTrue(out)          # 不是空
        self.assertIn("q1", out)      # 还带着信息
        self.assertIn("1", out)       # 带轮数

    def test_offline_backend_degrades_instead_of_expanding(self):
        """离线 FakeModel 没有摘要能力：必须降级为模板，而不是把旧对话原样放大。

        回归"压缩做成放大"：FakeModel.generate 不认摘要提示词，会返回
        「【离线演示】…」+ 整段旧对话，使 summary slot 比原文更长（实测 146 > 87
        tokens），旧轮次同时出现在 summary 和 history 两个槽里，等于重复注入。
        """
        turns = [HistoryTurn(user=f"q{i}", assistant=f"a{i}") for i in range(4)]
        old_text = "\n".join(f"用户：{t.user}\n助手：{t.assistant}" for t in turns)

        out = HistorySummarizer(FakeModel()).summarize_history(turns)

        self.assertTrue(out)                                  # 不是空
        self.assertNotIn("离线演示", out)                      # 不是离线话术
        self.assertNotIn("q0", out)                           # 旧对话没有被原样回灌
        self.assertLess(token_len(out), token_len(old_text))  # 真的压缩了

    def test_summary_slot_outranks_history(self):
        """摘要优先级必须高于 history，否则超预算时摘要会第一个被裁。"""
        ctx = ContextEngine(4096, reranker=Reranker()).build(
            user_input="x",
            retrieved=[],
            history=[HistoryTurn(f"q{i}", f"a{i}") for i in range(12)],
            system_prompt="sys",
        )
        prios = {s.kind: s.priority for s in ctx.slots}
        self.assertIn("summary", prios)
        self.assertIn("history", prios)
        self.assertGreater(prios["summary"], prios["history"])

    def test_history_window_follows_config(self):
        """滑窗轮数必须读 config.HISTORY_MAX_TURNS，而不是硬编码。

        这就是"假旋钮"的回归测试：把配置改小，保留的轮数必须跟着变小。
        硬编码 max_keep=8 的老实现会让这条测试失败。
        """
        original = config.HISTORY_MAX_TURNS
        try:
            config.HISTORY_MAX_TURNS = 3
            ctx = ContextEngine(4096, reranker=Reranker()).build(
                user_input="x",
                retrieved=[],
                history=[HistoryTurn(f"q{i}", f"a{i}") for i in range(7)],
                system_prompt="sys",
            )
            hist = next(s for s in ctx.slots if s.kind == "history")
            self.assertEqual(hist.content.count("用户："), 3)
        finally:
            config.HISTORY_MAX_TURNS = original


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
