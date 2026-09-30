"""Skill loader —— 把 ``skills/`` 目录下的 SKILL.md 读成 :class:`Skill` 对象。

三个刻意的设计约束：

* **零依赖**：front-matter 用一个极小的手写解析（CI 只装 ``requirements.txt``，
  不为了几个键值对引入 PyYAML）；
* **容错优先**：SKILL.md 是**人手写的**，缺字段 / 格式写错不能让服务起不来 ——
  跳过该技能并记录人话原因，由调用方决定怎么提示；
* **文件是唯一真源**：技能用 Git 管理（可 review、可 diff），索引与命中统计都是**派生数据**
  （阶段 2 才入库），所以永远不存在"数据库和文件哪个对"的问题。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: 必填字段：缺任何一个就跳过（并记录原因）
REQUIRED_FIELDS = ("name", "description")
#: 这几个字段解析成列表
LIST_FIELDS = ("tags", "trigger", "stack")
#: front-matter：文件以 ``---`` 开头，正文前再用 ``---`` 收尾
_FRONT_MATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)$", re.S)
_SPLIT_RE = re.compile(r"[,，]")


class SkillError(ValueError):
    """技能格式错误。由 :func:`load_skills` 捕获成 skipped 记录，不向上抛。"""


@dataclass
class Skill:
    name: str
    description: str
    body: str = ""
    tags: list[str] = field(default_factory=list)
    trigger: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    status: str = "active"
    version: str = "1"
    updated: str = ""
    path: str = ""

    @property
    def active(self) -> bool:
        """``deprecated`` 的技能保留在库里但不再参与匹配。"""
        return self.status.strip().lower() != "deprecated"

    @property
    def keywords(self) -> list[str]:
        """关键词匹配用的词：name / tags / trigger。

        description 不参与——它是一句话，命中它等于命中噪音；真要按语义匹配，
        阶段 2 会走独立语料的检索，而不是在这里堆字符串。
        """
        return [k for k in [self.name, *self.tags, *self.trigger] if k]

    def summary(self, limit: int = 60) -> str:
        text = self.description
        if len(text) > limit:
            text = text[: limit - 1] + "…"
        return f"{self.name}：{text}"

    def as_dict(self) -> dict:
        """给 API / 前端用的序列化（正文一并给出：这个页面的用途就是让人看清规则）。"""
        return {
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "tags": self.tags,
            "trigger": self.trigger,
            "stack": self.stack,
            "status": self.status,
            "version": self.version,
            "updated": self.updated,
            "path": self.path,
            "active": self.active,
        }


@dataclass
class LoadResult:
    skills: list[Skill] = field(default_factory=list)
    #: 被跳过的技能：[{"path": ..., "reason": ...}]。**不静默吞掉**——写错的技能要能被发现。
    skipped: list[dict] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.skills]


def parse_skill(text: str, path: str = "") -> Skill:
    """解析一份 SKILL.md；格式不对抛 :class:`SkillError`（消息是人话）。"""
    match = _FRONT_MATTER_RE.match(text.lstrip("\ufeff"))
    if not match:
        raise SkillError("缺少 front-matter（文件必须以 --- 开头，正文前再用 --- 结束）")
    meta = _parse_front_matter(match.group(1))
    missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        raise SkillError("front-matter 缺字段：" + "、".join(missing))
    return Skill(
        name=str(meta["name"]),
        description=str(meta["description"]),
        body=match.group(2).strip(),
        tags=_as_list(meta.get("tags")),
        trigger=_as_list(meta.get("trigger")),
        stack=_as_list(meta.get("stack")),
        status=str(meta.get("status") or "active"),
        version=str(meta.get("version") or "1"),
        updated=str(meta.get("updated") or ""),
        path=path,
    )


def _parse_front_matter(block: str) -> dict:
    """极小的 YAML 子集：``key: value`` 与 ``key: [a, b]``（写成 ``a, b`` 也认）。

    不支持嵌套与多行——技能的 front-matter 只该是平的键值对；真需要复杂结构，
    应该写进正文，而不是把解析器写复杂（这也是不引 PyYAML 的前提）。
    """
    out: dict = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key in LIST_FIELDS:
            out[key] = [
                v
                for v in (s.strip().strip("'\"") for s in _SPLIT_RE.split(value.strip("[]")))
                if v
            ]
        else:
            out[key] = value.strip("'\"")
    return out


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in _SPLIT_RE.split(str(value)) if s.strip()]


def load_skills(directory) -> LoadResult:
    """扫描 ``<directory>/*/SKILL.md``（单层，不递归）。

    为什么单层：一个技能一个目录是刻意的约束，避免"技能藏在技能里"这种无法管理的结构。
    目录不存在时返回空结果 + 一条 skipped，**不抛异常**——首次 clone、CI 缺目录都不该崩。
    """
    result = LoadResult()
    base = Path(directory)
    if not base.is_dir():
        result.skipped.append({"path": str(base), "reason": "技能目录不存在"})
        return result

    for skill_md in sorted(base.glob("*/SKILL.md")):
        try:
            skill = parse_skill(skill_md.read_text(encoding="utf-8"), path=str(skill_md))
        except SkillError as exc:
            result.skipped.append({"path": str(skill_md), "reason": str(exc)})
            continue
        except OSError as exc:  # 权限/编码问题：记原因，不影响其它技能
            result.skipped.append({"path": str(skill_md), "reason": f"读取失败：{exc}"})
            continue
        if skill.name != skill_md.parent.name:
            result.skipped.append({
                "path": str(skill_md),
                "reason": f"name({skill.name}) 与目录名({skill_md.parent.name}) 不一致",
            })
            continue
        result.skills.append(skill)
    return result
