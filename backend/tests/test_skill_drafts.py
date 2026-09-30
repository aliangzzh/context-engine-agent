"""草稿区（``skills/_inbox/``）接口测试：列表 / 归档 / 从对话沉淀。

这里守的是三条线：
1. **路径安全** —— 页面新增了写文件的能力，必须只能碰 `_inbox` 下的 `.md`；
2. **可后悔** —— "移除"是归档到 `_trash`，不是真删（草稿不在 Git 里）；
3. **幂等** —— 同一个坑点两次不该产生两份草稿。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app import api, config
from app.context.history import ChatStore, HistoryTurn
from app.errors import AppError, ErrorCode
from app.skills import drafts, reset_skill_retriever, reset_skills

_SCRATCH = Path(__file__).parent / "_scratch"
_counter = {"n": 0}


def _scratch_dir() -> Path:
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    _counter["n"] += 1
    d = _SCRATCH / f"drafts_{os.getpid()}_{_counter['n']}"
    d.mkdir(parents=True, exist_ok=True)
    return d


GOOD_TURNS = [
    HistoryTurn(
        user="跑测试把向量索引覆盖了怎么办，为什么 /health 一直是 stale",
        assistant=(
            "这是测试污染：拿临时语料跑流程时用了全局索引目录。"
            "修复：让索引跟着语料走，并给测试基类隔离 FAISS_PERSIST_DIR。"
            "验证：重建索引后跑一遍 unittest，chunk_count 仍是 488。" * 3
        ),
    ),
    HistoryTurn(user="那怎么验证修好了", assistant="跑一遍全量测试，看断言；再查 /health 的 chunk_count。"),
]

#: 不含任何现象词的一轮：自动规则会丢掉它，但**人工显式点击**必须能落草稿
PLAIN_TURNS = [HistoryTurn(user="项目里怎么切换模型", assistant="改成 .env 里的 CHAT_BACKEND，然后重启服务。")]


class _DraftCase(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch_dir()
        self._saved = {k: getattr(config, k) for k in ("SKILL_DIR", "DATA_DIR", "DB_PATH")}
        config.SKILL_DIR = self.tmp / "skills"
        config.DATA_DIR = self.tmp / "data"
        config.DB_PATH = config.DATA_DIR / "app.db"
        (config.SKILL_DIR / "_inbox").mkdir(parents=True, exist_ok=True)
        reset_skills()
        reset_skill_retriever()

    def tearDown(self):
        for key, value in self._saved.items():
            setattr(config, key, value)
        reset_skills()
        reset_skill_retriever()

    def _write(self, name: str, body: str = "# 标题\n\n内容\n") -> Path:
        path = drafts.inbox_dir() / name
        path.write_text(body, encoding="utf-8")
        return path

    def _store(self, turns, session: str = "d-1") -> None:
        ChatStore(config.DATA_DIR / "chat_history").save(session, turns)


class PathSafetyTest(_DraftCase):
    def test_rejects_path_traversal_and_non_markdown(self):
        for bad in ("../escape.md", "sub/dir.md", r"..\escape.md", "note.txt",
                    "no-extension", "..md", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(AppError) as ctx:
                    drafts.archive_draft(bad)
                self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION_ERROR)

    def test_list_only_sees_markdown_in_inbox_root(self):
        self._write("chat-a-1-x.md")
        self._write("notes.txt", "not markdown")
        (drafts.inbox_dir() / "_trash").mkdir(exist_ok=True)
        (drafts.inbox_dir() / "_trash" / "20260101-000000-old.md").write_text("归档", encoding="utf-8")
        names = [d["name"] for d in drafts.list_drafts()["drafts"]]
        self.assertEqual(names, ["chat-a-1-x.md"])


class ListDraftsTest(_DraftCase):
    def test_source_badge_and_content(self):
        self._write("chat-sess-1-问题.md", "# 报错怎么办\n\n正文\n")
        self._write("01-文档抽取.md", "# 文档条目\n\n正文\n")
        self._write("手工笔记.md", "# 手写的\n")
        items = {d["name"]: d for d in drafts.list_drafts()["drafts"]}
        self.assertEqual(items["chat-sess-1-问题.md"]["source"], "对话抽取")
        self.assertEqual(items["01-文档抽取.md"]["source"], "文档抽取")
        self.assertEqual(items["手工笔记.md"]["source"], "手工/其它")
        self.assertIn("报错怎么办", items["chat-sess-1-问题.md"]["question"])
        self.assertIn("正文", items["chat-sess-1-问题.md"]["content"])

    def test_duplicate_hint_ignores_self(self):
        body = "# 向量索引被测试覆盖了怎么办\n\n向量索引 测试 覆盖 全局目录 隔离 降级 chunk_count\n"
        self._write("chat-a-1-same.md", body)
        self._write("chat-b-1-same.md", body)
        items = {d["name"]: d for d in drafts.list_drafts()["drafts"]}
        # 内容一样的另一份草稿应被判重（自己不应该匹配自己）
        self.assertIsNotNone(items["chat-b-1-same.md"]["duplicate"])
        self.assertEqual(items["chat-b-1-same.md"]["duplicate"][0], "draft:chat-a-1-same.md")


class ArchiveTest(_DraftCase):
    def test_archive_moves_to_trash_and_is_listed_no_more(self):
        self._write("chat-a-1-x.md")
        result = drafts.archive_draft("chat-a-1-x.md")
        self.assertEqual(result["archived"], "chat-a-1-x.md")
        self.assertTrue(result["moved_to"].startswith("_trash/"))
        self.assertEqual(result["trash_count"], 1)
        self.assertFalse((drafts.inbox_dir() / "chat-a-1-x.md").exists())
        self.assertTrue((drafts.inbox_dir() / result["moved_to"]).exists(), "归档后文件必须在 _trash 里")
        self.assertEqual(drafts.list_drafts()["drafts"], [])

    def test_archive_missing_is_not_found(self):
        with self.assertRaises(AppError) as ctx:
            drafts.archive_draft("nope.md")
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)


class CreateFromChatTest(_DraftCase):
    def test_creates_draft_then_is_idempotent(self):
        self._store(GOOD_TURNS)
        first = drafts.create_from_chat("d-1", 1, GOOD_TURNS[0].user)
        self.assertIn("created", first)
        self.assertIsNotNone(first["created"])
        self.assertIsNone(first["duplicate"])
        path = drafts.inbox_dir() / first["created"]
        text = path.read_text(encoding="utf-8")
        self.assertIn("AI 抽取", text)
        self.assertIn("来源会话：d-1", text)
        self.assertIn("待提炼（四段式）", text)

        again = drafts.create_from_chat("d-1", 1, GOOD_TURNS[0].user)
        self.assertIsNone(again["created"], "重复点击不该写出第二份")
        self.assertIsNotNone(again["duplicate"])
        self.assertEqual(len(drafts.list_drafts()["drafts"]), 1)

    def test_explicit_click_wins_over_auto_rules(self):
        """人工显式信号优先：没有现象词的普通问答，点了也要能落草稿。"""
        self._store(PLAIN_TURNS)
        result = drafts.create_from_chat("d-1", 1, PLAIN_TURNS[0].user)
        self.assertIsNotNone(result["created"])
        self.assertEqual(result["categories"], 1)
        self.assertEqual(result["signals"]["symptom"], [])

    def test_bad_index_and_stale_history(self):
        self._store(GOOD_TURNS)
        with self.assertRaises(AppError) as ctx:
            drafts.create_from_chat("d-1", 99)
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION_ERROR)

        with self.assertRaises(AppError) as ctx2:
            drafts.create_from_chat("d-1", 1, "这句和库里那一轮对不上")
        self.assertEqual(ctx2.exception.code, ErrorCode.CONFLICT)

    def test_missing_session_is_not_found(self):
        self._store(GOOD_TURNS)
        with self.assertRaises(AppError) as ctx:
            drafts.create_from_chat("no-such-session", 1)
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)

    def test_secrets_are_scrubbed_in_draft(self):
        self._store([HistoryTurn(
            user="key 写错了怎么办",
            assistant=(
                "用 sk-abcdef123456 调接口；.env 里 DEEPSEEK_API_KEY=realkey123456 也要藏；"
                "Authorization: Bearer abcdef1234567890 同理"
            ),
        )])
        result = drafts.create_from_chat("d-1", 1)
        text = (drafts.inbox_dir() / result["created"]).read_text(encoding="utf-8")
        self.assertNotIn("sk-abcdef123456", text)
        self.assertNotIn("realkey123456", text)
        self.assertNotIn("abcdef1234567890", text)
        self.assertIn("sk-***", text)


class HandlerTest(_DraftCase):
    def test_list_handler_envelope(self):
        self._write("chat-a-1-x.md")
        status, body = api.handle_skill_drafts()
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)
        self.assertEqual(len(body["data"]["drafts"]), 1)
        self.assertEqual(body["data"]["trash_count"], 0)

    def test_archive_handler_propagates_app_error(self):
        with self.assertRaises(AppError) as ctx:
            api.handle_skill_draft_archive("nope.md")
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)
        self.assertEqual(ctx.exception.http_status, 404)

    def test_from_chat_handler_validates_payload(self):
        with self.assertRaises(AppError) as ctx:
            api.handle_skill_draft_from_chat({"turn_index": 1})
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION_ERROR)


if __name__ == "__main__":
    unittest.main()
