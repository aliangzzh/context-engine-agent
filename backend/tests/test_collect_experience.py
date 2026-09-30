"""从对话历史起草（``collect_experience from-chat``）的规则测试。

重点不在"能不能跑"，而在**筛选规则**：哪些片段会被当成草稿候选、哪些必须被丢掉。
这些规则直接决定技能库的信任度 —— 放进来一条错的，模型会拿它当硬约束用很久。
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app import config
from app.context.history import ChatStore, HistoryTurn
from app.skills import reset_skill_retriever, reset_skills
from scripts import collect_experience as ce

_SCRATCH = Path(__file__).parent / "_scratch"
_counter = {"n": 0}


def _scratch_dir() -> Path:
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    _counter["n"] += 1
    d = _SCRATCH / f"ce_{os.getpid()}_{_counter['n']}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _args(**kw) -> SimpleNamespace:
    base = {"session": None, "top": 5, "write": False, "force": False, "verbose": False}
    base.update(kw)
    return SimpleNamespace(**base)


#: 一条"像样的"开发经验片段：现象 → 动作 → 验证 三类信号齐全
GOOD_TURNS = [
    HistoryTurn(
        user="跑测试把向量索引覆盖了怎么办，为什么 /health 一直是 stale",
        assistant=(
            "这是测试污染：拿临时语料跑流程时用了全局索引目录。"
            "修复：让索引跟着语料走（Retriever 在自定义 kb_path 时把索引放到语料旁边），"
            "并给测试基类隔离 FAISS_PERSIST_DIR。"
            "验证：重建索引后跑一遍 unittest，chunk_count 仍是 488。" * 3
        ),
    ),
    HistoryTurn(user="那怎么验证修好了", assistant="跑一遍全量测试，看断言；再查 /health 的 chunk_count。"),
]

#: 一个业务会话：**故意**含现象词，但它属于业务问答，必须被丢掉
BUSINESS_TURNS = [
    HistoryTurn(
        user="尺码推荐为什么不对",
        assistant="洗涤养护建议水温不超过 30 度；材质说明见文档；尺码请按腰围选。",
    ),
]


class ScrubTest(unittest.TestCase):
    def test_masks_keys_bearer_and_internal_ips(self):
        text = "用 sk-abcdef123456 调接口，Authorization: Bearer abcdef1234567890，内网 10.20.30.40"
        out = ce.scrub(text)
        self.assertNotIn("sk-abcdef123456", out)
        self.assertNotIn("abcdef1234567890", out)
        self.assertNotIn("10.20.30.40", out)
        self.assertIn("sk-***", out)
        self.assertIn("***.***.***.***", out)


class SegmentTest(unittest.TestCase):
    def test_new_segment_starts_on_symptom_turn(self):
        turns = GOOD_TURNS + [HistoryTurn(user="顺便问下天气", assistant="晴")]
        segments = ce.segments_from_turns("s1", turns)
        # 第二条含现象词吗？不含 → 接在第一段后面；所以仍是 1 段
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["start"], 1)

        turns2 = [HistoryTurn(user="你好", assistant="你好"), *GOOD_TURNS]
        segments2 = ce.segments_from_turns("s2", turns2)
        self.assertEqual(len(segments2), 2, "闲聊后遇到现象词应开新片段")
        self.assertEqual(segments2[1]["start"], 2)

    def test_segment_is_capped_by_max_turns(self):
        long_turns = [
            HistoryTurn(user=f"报错 {i}", assistant="修复并验证") for i in range(ce.MAX_SEGMENT_TURNS + 3)
        ]
        segments = ce.segments_from_turns("s3", long_turns)
        self.assertTrue(all(len(s["turns"]) <= ce.MAX_SEGMENT_TURNS for s in segments))
        self.assertGreater(len(segments), 1, "超长会话应被切成多段而不是一段到底")


class ScoreTest(unittest.TestCase):
    def test_full_signal_triple_is_a_candidate(self):
        item = ce.score_segment(ce.segments_from_turns("s", GOOD_TURNS)[0])
        self.assertEqual(item["categories"], 3)
        self.assertTrue(item["symptom"] and item["action"] and item["verify"])
        self.assertGreaterEqual(item["score"], 6.0)
        self.assertTrue(ce.is_candidate(item))

    def test_business_session_is_rejected_even_with_symptom_words(self):
        item = ce.score_segment(ce.segments_from_turns("s", BUSINESS_TURNS)[0])
        self.assertTrue(item["symptom"], "构造的用例里确实有现象词")
        self.assertTrue(item["offtopic"], "但业务词表要命中")
        self.assertFalse(ce.is_candidate(item), "业务问答不能变成开发经验")

    def test_plain_question_without_symptom_is_not_a_candidate(self):
        item = ce.score_segment(
            ce.segments_from_turns("s", [HistoryTurn(user="加绒牛仔怎么洗", assistant="水温不超过30度")])[0]
        )
        self.assertEqual(item["symptom"], [])
        self.assertFalse(ce.is_candidate(item))


class DuplicateTest(unittest.TestCase):
    def test_similar_text_is_flagged(self):
        existing = {"skill:global-index-isolation": "向量索引 测试 覆盖 全局目录 隔离 stale 降级 chunk_count"}
        dup = ce.find_duplicate(
            "向量索引被测试覆盖了怎么办，为什么 stale",
            "向量索引被测试覆盖 全局目录 隔离 降级 chunk_count",
            existing,
        )
        self.assertIsNotNone(dup)
        self.assertEqual(dup[0], "skill:global-index-isolation")

    def test_same_question_different_answer_is_still_flagged(self):
        """同一个坑问了多次、每次答案不同 —— 也必须算重复（实测漏判过这一种）。"""
        picked = {"本批#1": "跑测试把向量索引覆盖了怎么办，有经验吗 " + "这次回答写得比较长，细节不同。" * 20}
        dup = ce.find_duplicate("跑测试把向量索引覆盖了怎么办，有经验吗", "另一段完全不同的回答", picked)
        self.assertIsNotNone(dup, "问题相同就该判重，不能因为答案不同就放过")
        self.assertEqual(dup[0], "本批#1")

    def test_unrelated_text_is_not_flagged(self):
        existing = {"skill:tool-arg-extraction": "工具调用 参数 抽取 追问"}
        self.assertIsNone(ce.find_duplicate("加绒牛仔怎么洗", "加绒牛仔 洗涤 水温 材质", existing))


class FromChatCommandTest(unittest.TestCase):
    """端到端：dry-run 不写文件；--write 才落进 skills/_inbox/。"""

    def setUp(self):
        self.tmp = _scratch_dir()
        self._saved = {k: getattr(config, k) for k in ("DATA_DIR", "SKILL_DIR", "DB_PATH")}
        config.DATA_DIR = self.tmp / "data"
        config.SKILL_DIR = self.tmp / "skills"
        config.DB_PATH = config.DATA_DIR / "app.db"
        (config.SKILL_DIR / "_inbox").mkdir(parents=True, exist_ok=True)
        store = ChatStore(config.DATA_DIR / "chat_history")
        store.save("ce-1", GOOD_TURNS)
        store.save("ce-2", BUSINESS_TURNS)
        reset_skills()
        reset_skill_retriever()

    def tearDown(self):
        for key, value in self._saved.items():
            setattr(config, key, value)
        reset_skills()
        reset_skill_retriever()

    def _inbox_files(self) -> list[Path]:
        return sorted((config.SKILL_DIR / "_inbox").glob("*.md"))

    def test_dry_run_lists_candidates_but_writes_nothing(self):
        code = ce.cmd_from_chat(_args(write=False))
        self.assertEqual(code, 0)
        self.assertEqual(self._inbox_files(), [], "dry-run 绝不能写文件")

    def test_write_creates_a_draft_with_metadata(self):
        code = ce.cmd_from_chat(_args(write=True))
        self.assertEqual(code, 0)
        files = self._inbox_files()
        self.assertEqual(len(files), 1, f"业务会话应被丢弃，只留开发经验：{files}")
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("AI 抽取", text)
        self.assertIn("来源会话：ce-1", text)
        self.assertIn("待提炼（四段式）", text)
        self.assertIn("跑测试把向量索引覆盖了", text)

    def test_session_filter(self):
        code = ce.cmd_from_chat(_args(session="ce-2", write=True))
        self.assertEqual(code, 0)
        self.assertEqual(self._inbox_files(), [], "ce-2 是业务会话，不该产出草稿")


if __name__ == "__main__":
    unittest.main()
