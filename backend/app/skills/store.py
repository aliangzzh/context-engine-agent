"""技能语料：把 ``skills/`` 的文件同步进**独立的**检索语料，供 RAG 检索使用。

为什么必须与业务知识库物理隔离（三条都记在 ``docs/skill-plan.md`` §2）：

* **BM25 是扁平语料**：一个 ``Retriever`` 实例只有一份 docs，两库混用会互相挤掉 top-k；
* **缓存 key 原本没有语料维度**：``retrieve:{backend}:{k}:{query}`` → 问技能库却命中业务库；
* **向量索引指纹按目录存放**：共用索引目录会互相判 STALE，永远降级。

同步是**幂等**的：按每个技能的 md5 清单比对（只看变化），技能被删掉时同步移除它的
chunk —— 否则会出现"文件删了、检索还命中"的幽灵结果（和向量索引那类一致性问题同源）。
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..retrieval.retriever import Retriever
from .loader import Skill

_lock = threading.Lock()
_retriever: Retriever | None = None


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def skill_text(skill: Skill) -> str:
    """一个技能 = **一个 chunk**。

    刻意不按段落切分：技能的规则是一个整体语义单元——只检索到"反例"却没拿到"规则"，
    比不检索更危险。真太长就拆成两个技能，或把细节放进 ``references/``。
    """
    parts = [f"[技能 {skill.name}] {skill.description}"]
    keys = [*skill.tags, *skill.trigger]
    if keys:
        parts.append("关键词：" + "、".join(keys))
    if skill.body:
        parts.append(skill.body)
    return "\n".join(parts).strip()


def skill_md5(skill: Skill) -> str:
    return _md5(skill_text(skill))


def manifest_path() -> Path:
    return Path(config.SKILL_KB_PATH).parent / "manifest.json"


def read_manifest() -> dict:
    """已同步的技能 → md5 清单（缺文件/坏文件都当空处理，同步会重建）。"""
    path = manifest_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(k): str(v) for k, v in (data.get("skills") or {}).items()}


def _write_manifest(manifest: dict, chunks: int) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "skills": manifest,
                "chunks": chunks,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def get_skill_retriever() -> Retriever:
    """技能语料的检索器（进程内单例）。

    为什么单例：``get_retriever()`` 每次都会新建实例、重读语料并重建 BM25；
    技能库若每请求新建，等于每个问题都重读一次盘。命名空间与索引目录都和业务库错开。
    """
    global _retriever
    with _lock:
        if _retriever is None:
            _retriever = Retriever(
                kb_path=Path(config.SKILL_KB_PATH),
                namespace="skills",
                index_name=config.SKILL_INDEX_NAME,
                index_dir=config.SKILL_INDEX_DIR,
            )
        return _retriever


def reset_skill_retriever() -> None:
    """清掉单例（测试与 reload 用）。"""
    global _retriever
    with _lock:
        _retriever = None


def needs_sync(skills: list[Skill]) -> bool:
    """语料是否需要重建：按 md5 清单比对（增、改、删都算）。"""
    return {s.name: skill_md5(s) for s in skills} != read_manifest()


def sync_skills(skills: list[Skill], *, force: bool = False) -> dict:
    """把技能同步进技能语料，返回可打印的摘要。幂等：没变化就什么都不做。

    ``force`` 的语义是"**即使内容没变也重建索引**"，**不是**"忘掉历史" ——
    所以 md5 历史永远参与比对，删除检测（removed）才能一直生效。
    """
    current = {s.name: skill_md5(s) for s in skills}
    previous = read_manifest()
    changed = sorted(current) if force else sorted(
        n for n, h in current.items() if previous.get(n) != h
    )
    removed = sorted(n for n in previous if n not in current)
    if not changed and not removed:
        return {"changed": [], "removed": [], "chunks": len(current), "rebuilt": False}

    retriever = get_skill_retriever()
    texts = [skill_text(s) for s in skills]
    metas = [
        {"source": f"skill:{s.name}", "path": s.path, "md5": current[s.name], "tags": s.tags}
        for s in skills
    ]
    retriever.replace_all(texts, metas)
    # 向量索引：可用时重建；离线 / 无 key 时内部自己降级 BM25，不抛异常
    try:
        retriever.rebuild_vector_index()
    except Exception:  # pragma: no cover - 取决于环境是否装了可选依赖
        pass
    _write_manifest(current, len(texts))
    return {"changed": changed, "removed": removed, "chunks": len(texts), "rebuilt": True}


def ensure_synced(skills: list[Skill], *, force: bool = False) -> dict:
    """调用方（工具 / 接口）用这个：需要就同步，不需要就跳过。"""
    if not force and not needs_sync(skills):
        retriever = get_skill_retriever()
        return {"changed": [], "removed": [], "chunks": len(retriever.texts), "rebuilt": False}
    return sync_skills(skills, force=force)


def search_skill_corpus(query: str, k: int | None = None) -> list:
    """在技能语料上检索（BM25 / 向量由配置决定，离线自动降级 BM25）。

    这里**不做**相关性判定：门控交给调用方（``context.rerank.is_relevant``），
    因为"够不够相关"和"从哪套语料里取"是两件事。
    """
    retriever = get_skill_retriever()
    if not retriever.texts:
        return []
    return retriever.search(query, k=k or config.SKILL_TOP_K)


def corpus_status(skills: list[Skill] | None = None) -> dict:
    """技能语料状态（给 /health、stats 与 CLI 用）。"""
    retriever = get_skill_retriever()
    info = {
        "chunks": len(retriever.texts),
        "backend": retriever.effective_backend(),
        "kb_path": str(retriever.kb_path),
        "manifest_count": len(read_manifest()),
    }
    if skills is not None:
        info["needs_sync"] = needs_sync(skills)
        info["loaded"] = len(skills)
    return info
