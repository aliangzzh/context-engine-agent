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
from app.agents.tools import TOOLS, extract_args, get_tool
from app.skills import get_skills, parse_skill, reset_skills, search_skills
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


class SkillToolTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
