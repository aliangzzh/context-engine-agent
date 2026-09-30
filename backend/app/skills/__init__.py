"""Skill 子系统：加载（loader）→ 匹配（matcher）→ 语料同步与检索（store）。

技能正文的**唯一真源是仓库根目录的 ``skills/``**（一个技能一个文件夹），
``backend/data/skills/`` 下的 kb.json 与索引都是**派生数据**（可随时重建、进 .gitignore）。
这样技能天然享受 Git 的 review / diff / 回滚，也不存在"数据库和文件哪个对"的问题。
"""
from __future__ import annotations

import threading

from .. import config
from .loader import LoadResult, Skill, SkillError, load_skills, parse_skill
from .matcher import Match, score_skill, search_skills
from .store import (
    corpus_status,
    ensure_synced,
    get_skill_retriever,
    needs_sync,
    reset_skill_retriever,
    search_skill_corpus,
    select_skills,
    skill_md5,
    skill_text,
    sync_skills,
)

__all__ = [
    "LoadResult", "Match", "Skill", "SkillError",
    "corpus_status", "ensure_synced", "get_skill_retriever", "get_skills",
    "load_skills", "needs_sync", "parse_skill", "reset_skill_retriever",
    "reset_skills", "score_skill", "search_skill_corpus", "search_skills",
    "select_skills", "skill_md5", "skill_text", "sync_skills",
]

_lock = threading.Lock()
_cache: LoadResult | None = None


def get_skills(reload: bool = False) -> LoadResult:
    """进程内缓存的技能集合。

    技能目录不会每个请求都变，没必要每次读盘；``reload=True`` 给管理接口与测试用。
    改完文件是否要重新同步语料，由 :func:`store.needs_sync` 按 md5 判定 ——
    不靠"记得重启"，也不靠"记得手动重建索引"。
    """
    global _cache
    with _lock:
        if _cache is None or reload:
            _cache = load_skills(config.SKILL_DIR)
        return _cache


def reset_skills() -> None:
    """清掉进程内缓存（测试与 reload 用）。"""
    global _cache
    with _lock:
        _cache = None
