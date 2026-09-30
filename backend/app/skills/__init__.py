"""Skill 子系统：加载（loader）→ 匹配（matcher）→ 阶段 2 起还会入库检索。

技能正文的**唯一真源是仓库根目录的 ``skills/``**（一个技能一个文件夹），
索引与命中统计是派生数据。这样技能天然享受 Git 的 review / diff / 回滚。
"""
from __future__ import annotations

import threading

from .. import config
from .loader import LoadResult, Skill, SkillError, load_skills, parse_skill
from .matcher import Match, score_skill, search_skills

__all__ = [
    "LoadResult", "Match", "Skill", "SkillError",
    "get_skills", "load_skills", "parse_skill", "reset_skills",
    "score_skill", "search_skills",
]

_lock = threading.Lock()
_cache: LoadResult | None = None


def get_skills(reload: bool = False) -> LoadResult:
    """进程内缓存的技能集合。

    技能目录不会每个请求都变，没必要每次读盘；``reload=True`` 给管理接口与测试用。
    注意进程内缓存 + 多 worker 部署时的一致性：阶段 2 会用 md5 清单做失效判断，
    而不是靠"记得重启"。
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
