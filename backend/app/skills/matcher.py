"""技能匹配：给定用户问题 / 编码任务，决定**该不该加载**某个技能。

阶段 1 只做关键词命中（可解释、零依赖、离线可用）。刻意**不**做语义匹配，
因为这一层的失效模式不对称：

* **漏命中**（该用的经验没用上）→ 退化成"和没有技能库一样"，可接受；
* **误命中**（拿不相干的经验去改代码）→ 会**主动把 Agent 带偏**，代价更大。

所以这里的默认策略是**宁可漏、不要错**：必须真的命中关键词才算，分数不够就不返回。
阶段 3 会在这里补上覆盖率门控（复用 ``context/rerank.is_relevant``）与独立语料的检索。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .loader import Skill


@dataclass
class Match:
    skill: Skill
    score: float
    hits: list[str] = field(default_factory=list)


def score_skill(query: str, skill: Skill) -> tuple[float, list[str]]:
    """关键词命中打分：技能名命中权重更高（名字本身就是术语）。"""
    text = (query or "").strip().lower()
    if not text or not skill.active:
        return 0.0, []
    hits = [k for k in skill.keywords if k and k.lower() in text]
    if not hits:
        return 0.0, []
    score = 0.0
    for k in hits:
        score += 2.0 if k.lower() == skill.name.lower() else 1.0
    return score, hits


def search_skills(
    query: str,
    skills: list[Skill],
    *,
    top_k: int = 2,
    min_score: float = 1.0,
) -> list[Match]:
    """返回命中的技能（按分数降序，最多 ``top_k`` 条）。

    ``min_score=1.0`` 的含义：至少命中一个关键词。**不设"最高分兜底"**——
    没有命中就返回空，让调用方如实说"没有相关经验"，而不是硬凑一条。
    """
    matched: list[Match] = []
    for skill in skills:
        score, hits = score_skill(query, skill)
        if score >= min_score:
            matched.append(Match(skill=skill, score=score, hits=hits))
    matched.sort(key=lambda m: (-m.score, m.skill.name))
    return matched[: max(1, top_k)]
