"""Skills 子系统的单测：加载容错 / 匹配正反例 / 工具与 MCP 暴露。

约定与其它测试一致：不联网、不依赖第三方库，临时文件写在 ``tests/_scratch``
（本沙箱下系统临时目录不可写）。
"""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app import config
from app.agents.orchestrator import AgentOrchestrator
from app.agents.router import route
from app.agents.tools import TOOLS, extract_args, get_tool
from app.context.engine import ContextEngine
from app.context.history import ChatStore, HistoryManager
from app.context.rerank import Reranker
from app.models.fake import FakeModel
from app.retrieval.retriever import Retriever
from app.schemas import RetrievedChunk
from app.skills import (
    ensure_synced,
    get_skill_retriever,
    get_skills,
    needs_sync,
    parse_skill,
    reset_skill_retriever,
    reset_skills,
    search_skill_corpus,
    search_skills,
    skill_text,
    sync_skills,
)
from app.skills.loader import SkillError, load_skills

_SCRATCH = Path(__file__).parent / "_scratch"
_counter = {"n": 0}

_GOOD = """---
name: demo-skill
description: 一句话说清什么时候用它
tags: [alpha, beta]
trigger: [演示, demo]
status: active
version: 3
---

## 规则
1. 先看这里。
"""


def _scratch_dir() -> Path:
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    _counter["n"] += 1
    d = _SCRATCH / f"sk_{os.getpid()}_{time.time_ns()}_{_counter['n']}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_skill(root: Path, dirname: str, text: str) -> Path:
    d = root / dirname
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(text, encoding="utf-8")
    return p


class _OfflineSkillCorpus(unittest.TestCase):
    """强制 BM25：测试不联网、不调 embedding、结果确定。

    本机 ``.env`` 里可能配了 DashScope key（还装了 faiss），不锁的话每次
    ``sync`` 都会真的调 embedding —— 又慢又花钱，而且结果不确定。
    """

    def setUp(self):
        self._saved_backend = config.RETRIEVAL_BACKEND
        config.RETRIEVAL_BACKEND = "bm25"
        reset_skills()
        reset_skill_retriever()

    def tearDown(self):
        config.RETRIEVAL_BACKEND = self._saved_backend
        reset_skill_retriever()
        reset_skills()


class SkillLoaderTest(unittest.TestCase):
    def test_parses_front_matter_and_lists(self):
        skill = parse_skill(_GOOD, path="demo/SKILL.md")
        self.assertEqual(skill.name, "demo-skill")
        self.assertEqual(skill.tags, ["alpha", "beta"])
        self.assertEqual(skill.trigger, ["演示", "demo"])
        self.assertEqual(skill.version, "3")
        self.assertTrue(skill.active)
        self.assertIn("规则", skill.body)

    def test_missing_front_matter_raises_human_reason(self):
        with self.assertRaises(SkillError) as ctx:
            parse_skill("# 没有 front-matter\n", path="x/SKILL.md")
        self.assertIn("front-matter", str(ctx.exception))

    def test_missing_required_field_raises(self):
        with self.assertRaises(SkillError) as ctx:
            parse_skill("---\nname: only-name\n---\n\n正文\n", path="x/SKILL.md")
        self.assertIn("description", str(ctx.exception))

    def test_load_skips_bad_files_without_crashing(self):
        """人手写的技能写错是常态：坏文件被跳过并记录原因，好文件照常加载。"""
        root = _scratch_dir()
        _write_skill(root, "demo-skill", _GOOD)
        _write_skill(root, "broken", "# 忘了 front-matter\n")
        _write_skill(root, "incomplete", "---\nname: incomplete\n---\n\n正文\n")
        _write_skill(root, "name-mismatch", _GOOD.replace("demo-skill", "other-name"))

        result = load_skills(root)

        self.assertEqual(result.names, ["demo-skill"])
        self.assertEqual(len(result.skipped), 3)
        reasons = " | ".join(s["reason"] for s in result.skipped)
        self.assertIn("front-matter", reasons)
        self.assertIn("description", reasons)
        self.assertIn("不一致", reasons)

    def test_missing_directory_is_not_an_error(self):
        result = load_skills(_scratch_dir() / "not-there")
        self.assertEqual(result.skills, [])
        self.assertEqual(result.skipped[0]["reason"], "技能目录不存在")

    def test_deprecated_skill_is_inactive(self):
        skill = parse_skill(_GOOD.replace("status: active", "status: deprecated"), path="d/SKILL.md")
        self.assertFalse(skill.active)


class SkillMatcherTest(unittest.TestCase):
    def test_positive_hit_on_real_repo_skill(self):
        """仓库里真实存在的技能：问「工具参数怎么抽」应该命中它。"""
        result = get_skills()
        self.assertIn("tool-arg-extraction", result.names)
        matches = search_skills("工具调用的时候参数怎么抽？", result.skills)
        self.assertTrue(matches)
        self.assertEqual(matches[0].skill.name, "tool-arg-extraction")
        self.assertTrue(matches[0].hits)

    def test_negative_no_hit_on_unrelated_question(self):
        """反面：不相干的问题必须**不命中**（误命中会把 Agent 带偏）。"""
        result = get_skills()
        matches = search_skills("今天北京天气怎么样", result.skills)
        self.assertEqual(matches, [])

    def test_skills_are_cached_but_reloadable(self):
        first = get_skills()
        self.assertIs(first, get_skills())
        reset_skills()
        self.assertIsNot(first, get_skills())


class SkillToolTest(_OfflineSkillCorpus):
    def test_tool_registered_with_params(self):
        self.assertIn("search_skill", TOOLS)
        tool = get_tool("search_skill")
        self.assertTrue(tool.params)
        # 检索类工具是「整句就是 query」的例外
        self.assertEqual(extract_args("search_skill", " 怎么抽参数 "), {"query": "怎么抽参数"})
        self.assertEqual(extract_args("search_skill", "   "), {})

    def test_tool_returns_skill_body(self):
        out = get_tool("search_skill").run(query="工具参数抽取踩过的坑")
        self.assertIn("tool-arg-extraction", out)
        self.assertIn("规则", out)

    def test_tool_says_so_when_nothing_matches(self):
        out = get_tool("search_skill").run(query="今天天气怎么样")
        self.assertIn("没有", out)

    def test_mcp_schema_exposed(self):
        """MCP 客户端看不到参数 schema 就调不动——新工具必须补 schema。"""
        import mcp_server

        self.assertIn("search_skill", mcp_server._TOOL_SCHEMAS)
        names = [t["name"] for t in mcp_server.tools_list()]
        self.assertIn("search_skill", names)
        schema = next(t for t in mcp_server.tools_list() if t["name"] == "search_skill")
        self.assertEqual(schema["inputSchema"]["required"], ["query"])


class SkillConfigTest(unittest.TestCase):
    def test_skill_dir_points_at_repo_skills(self):
        self.assertEqual(config.SKILL_DIR.name, "skills")
        self.assertTrue(config.SKILL_ENABLED)
        self.assertGreaterEqual(config.SKILL_TOP_K, 1)


def _simulate_stale_memory(retriever, keep) -> None:
    """只在**内存**里退回旧语料（不动磁盘）。

    模拟"长跑进程启动时加载的是旧的一版"：磁盘上的 kb.json 是最新的，
    但这个进程的 texts/metas/bm25 还是旧的。注意不能用 ``replace_all()`` ——
    它会把磁盘语料一起改掉，那就变成"磁盘也旧了"，测不到要测的路径。
    """
    from app.retrieval.retriever import BM25Index

    retriever.texts = [skill_text(s) for s in keep]
    retriever.metas = [{"source": f"skill:{s.name}"} for s in keep]
    retriever.bm25 = BM25Index()
    retriever.bm25.add_documents(retriever.texts, retriever.metas)


class SkillCorpusTest(_OfflineSkillCorpus):
    """技能语料（派生数据）：与业务库物理隔离、幂等同步、删除不留幽灵。"""

    def setUp(self):
        super().setUp()
        self.loaded = get_skills(reload=True)
        self.assertTrue(self.loaded.skills, "仓库里应该有技能（skills/*/SKILL.md）")

    def tearDown(self):
        # 恢复全量语料，避免影响其它测试与后续运行
        sync_skills(get_skills(reload=True).skills, force=True)
        super().tearDown()

    def test_corpus_is_isolated_from_business_kb(self):
        """三处都必须与业务库错开：语料文件 / 缓存命名空间 / 向量索引目录。"""
        sk = get_skill_retriever()
        self.assertEqual(sk.namespace, "skills")
        self.assertNotEqual(Path(sk.kb_path), config.KB_DIR / "kb.json")
        self.assertNotEqual(Path(sk.vector.dir), Path(config.FAISS_PERSIST_DIR))

    def test_cache_key_separates_corpora_and_keeps_default_unchanged(self):
        biz = Retriever(backend="bm25", kb_path=config.KB_DIR / "kb.json")
        sk = get_skill_retriever()
        # 业务库（无 namespace）拼出来和改造前完全一致 —— 零行为变化
        self.assertEqual(biz._cache_key(3, "q"), "retrieve:bm25:3:q")
        self.assertEqual(sk._cache_key(3, "q"), "retrieve:skills:bm25:3:q")

    def test_sync_is_idempotent(self):
        first = sync_skills(self.loaded.skills, force=True)
        self.assertTrue(first["rebuilt"])
        second = sync_skills(self.loaded.skills)
        self.assertFalse(second["rebuilt"])
        self.assertEqual(second["changed"], [])
        self.assertEqual(second["removed"], [])

    def test_corpus_search_hits_expected_skill(self):
        sync_skills(self.loaded.skills, force=True)
        hits = search_skill_corpus("工具参数抽取", k=3)
        self.assertTrue(hits)
        self.assertIn("tool-arg-extraction", " ".join(str(h.source) for h in hits))

    def test_ensure_synced_reloads_when_memory_is_behind_disk(self):
        """进程内语料落后于磁盘时必须重读，而不是"md5 一致就跳过"。

        真实故障：长跑服务启动时语料是 4 条技能，之后仓库新增了第 5 条、磁盘清单也被
        另一个进程同步过 → ``needs_sync=False`` → ``ensure_synced`` 直接返回 →
        新技能表现为"**命中 1 条、注入 0 条**"。
        """
        loaded = get_skills(reload=True)
        sync_skills(loaded.skills, force=True)          # 磁盘 = 全部技能
        retriever = get_skill_retriever()
        keep = [s for s in loaded.skills if s.name != "global-index-isolation"]
        _simulate_stale_memory(retriever, keep)         # 内存退回旧版本
        self.assertFalse(needs_sync(loaded.skills), "磁盘仍然是最新的")

        summary = ensure_synced(loaded.skills)

        self.assertTrue(summary.get("reloaded"), f"应触发重读：{summary}")
        self.assertEqual(len(retriever.texts), len(loaded.skills))
        hits = search_skill_corpus("向量索引被覆盖 怎么排查", k=5)
        self.assertIn("skill:global-index-isolation", [str(h.source) for h in hits])

    def test_reload_clears_stale_retrieval_cache(self):
        """重读语料必须清检索缓存，否则"换语料前查不到"的结果会一直命中。"""
        loaded = get_skills(reload=True)
        sync_skills(loaded.skills, force=True)
        retriever = get_skill_retriever()
        keep = [s for s in loaded.skills if s.name != "global-index-isolation"]
        _simulate_stale_memory(retriever, keep)

        query = "向量索引被覆盖 怎么排查"
        before = [str(h.source) for h in search_skill_corpus(query, k=5)]
        self.assertNotIn("skill:global-index-isolation", before, "旧语料里不该有它，且这次结果进了缓存")

        ensure_synced(loaded.skills)

        after = [str(h.source) for h in search_skill_corpus(query, k=5)]
        self.assertIn("skill:global-index-isolation", after, "重读 + 清缓存之后必须能命中")

    def test_removed_skill_leaves_no_ghost_hits(self):
        """技能被删掉后语料必须同步移除，否则会出现"删了还命中"的幽灵结果。"""
        sync_skills(self.loaded.skills, force=True)
        keep = [s for s in self.loaded.skills if s.name != "tool-arg-extraction"]
        summary = sync_skills(keep, force=True)
        self.assertIn("tool-arg-extraction", summary["removed"])
        hits = search_skill_corpus("工具参数抽取", k=5)
        self.assertNotIn("skill:tool-arg-extraction", [str(h.source) for h in hits])


class SkillContextTest(_OfflineSkillCorpus):
    """技能进上下文：槽位 / 渲染 / 预算 / 编排器的 skill 节点。"""

    def _chunk(self, text: str = "规则：抽不到参数就向用户追问", name: str = "tool-arg-extraction"):
        return RetrievedChunk(text=text, source=f"skill:{name}", score=1.0)

    def test_skill_slot_is_rendered_into_prompt(self):
        eng = ContextEngine(4096, reranker=Reranker())
        ctx = eng.build(
            user_input="q", retrieved=[], history=[], system_prompt="S", skills=[self._chunk()]
        )
        slot = next((s for s in ctx.slots if s.kind == "skill"), None)
        self.assertIsNotNone(slot, "技能应作为独立槽位进入上下文")
        # 必须高于检索槽（rerank 给检索最高 110）：规则比资料先活下来
        self.assertEqual(slot.priority, config.SKILL_SLOT_PRIORITY)
        self.assertGreater(slot.priority, 110)
        # 这条断言防的是"槽位建了、render_messages 却没写分支"的静默丢弃
        messages = eng.render_messages(ctx, "q")
        self.assertIn("抽不到参数就向用户追问", messages[0]["content"])

    def test_skill_outranks_retrieval_when_budget_is_tight(self):
        """预算不够时**先裁检索槽**，技能槽要活下来（否则规则会被资料挤掉）。"""
        eng = ContextEngine(250, reranker=Reranker())
        ctx = eng.build(
            user_input="q", retrieved=[], history=[], system_prompt="S",
            skills=[self._chunk(text="技" * 200)],
        )
        self.assertIn("skill", [s.kind for s in ctx.slots])

        ctx2 = eng.build(
            user_input="q",
            retrieved=[RetrievedChunk(text="参" * 300, source="doc.txt", score=1.0)],
            history=[], system_prompt="S", skills=[self._chunk(text="技" * 200)],
        )
        kinds = [s.kind for s in ctx2.slots]
        self.assertIn("skill", kinds, "技能是行为约束，不能被参考资料挤掉")
        self.assertNotIn("retrieval", kinds, "预算不够时应先裁参考资料")

    def test_skill_slot_is_trimmed_under_tight_budget(self):
        eng = ContextEngine(2, reranker=Reranker())
        ctx = eng.build(
            user_input="q", retrieved=[], history=[], system_prompt="S",
            skills=[self._chunk(text="技" * 500)],
        )
        kinds = [s.kind for s in ctx.slots]
        self.assertIn("system", kinds)        # system 受保护
        self.assertNotIn("skill", kinds)      # 技能可裁
        self.assertGreater(ctx.trimmed, 0)    # 裁了多少如实上报，不静默

    def test_router_emits_skill_step_only_on_skill_keywords(self):
        self.assertIn("skill", route("查一下工具参数抽取的经验"))
        self.assertNotIn("skill", route("你好"))

    def _orchestrator(self, **kwargs):
        d = _scratch_dir()
        r = Retriever(backend="bm25", kb_path=d / "kb.json")
        hm = HistoryManager(ChatStore(d / "hist"), "s1", max_turns=4)
        return AgentOrchestrator(r, FakeModel(), hm, ContextEngine(2000, reranker=Reranker()), **kwargs)

    def test_orchestrator_injects_skill_and_traces_it(self):
        res = self._orchestrator().generate("查一下工具调用参数抽取的踩坑经验", "s1")
        kinds = [s["kind"] for s in res.trace.to_list()]
        self.assertIn("skill", kinds)
        self.assertIn("tool-arg-extraction", [s["name"] for s in res.skills])
        self.assertIn("skill", [s.kind for s in res.context.slots])
        self.assertIn("参数", res.messages[0]["content"])

    def test_orchestrator_can_disable_skills_for_ab_comparison(self):
        res = self._orchestrator(skills=False).generate("查一下工具调用参数抽取的踩坑经验", "s1")
        kinds = [s["kind"] for s in res.trace.to_list()]
        self.assertIn("skill", kinds)                    # 节点仍在（trace 可解释）
        self.assertEqual(res.skills, [])                 # 但什么都没注入
        self.assertNotIn("skill", [s.kind for s in res.context.slots])


class SkillApiTest(_OfflineSkillCorpus):
    """接口层形状：/api/skills 与 /api/skills/sync（前端技能页依赖它）。"""

    def test_list_handler_shape(self):
        from app import api

        status, body = api.handle_skill_list({})
        self.assertEqual(status, 200)
        data = body["data"]
        self.assertTrue(data["skills"], "接口要返回技能列表")
        self.assertEqual(data["skipped"], [])
        self.assertIn("chunks", data["stats"])
        for key in ("name", "description", "body", "trigger", "version", "path", "active"):
            self.assertIn(key, data["skills"][0])

    def test_sync_handler_reports_summary(self):
        from app import api

        status, body = api.handle_skill_sync({})
        self.assertEqual(status, 200)
        self.assertIn("rebuilt", body["data"]["summary"])
        self.assertTrue(body["data"]["skills"])


class CollectExperienceTest(unittest.TestCase):
    """归档脚本：真文档要能抽出条目（否则"自动归档"是假的）。"""

    def test_extracts_items_from_real_doc(self):
        from scripts.collect_experience import collect_items

        doc = Path(__file__).parents[2] / "docs" / "ai-assisted.md"
        items = collect_items(doc.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(items), 4)
        titles = " ".join(i["title"] for i in items)
        self.assertIn("沉默的错误", titles)
        self.assertIn("假参数", titles)
        # 抽出来的正文不能是空的（否则草稿没有素材价值）
        self.assertTrue(all(i["body"].strip() for i in items))


if __name__ == "__main__":
    unittest.main()
