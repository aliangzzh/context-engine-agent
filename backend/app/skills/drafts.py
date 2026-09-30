"""技能草稿区（``skills/_inbox/``）的文件操作：列表 / 归档 / 从对话沉淀。

草稿区与正式技能的分工，是整个设计的地基：

* **草稿在 ``_inbox/``**：不进检索语料（loader 只认 ``*/SKILL.md``）、不在 Git 里（.gitignore），
  所以脚本与页面都可以随便写它，写坏了没有任何副作用；
* **正式技能 ``skills/<name>/SKILL.md`` 是真源**：会被注入模型当硬约束，只能人工过审后提升。

因此这里的"删除"是**归档而不是真删**（移到 ``_inbox/_trash/``）—— 草稿不在 Git 里，
删了就真没了，而"移除"这个动作应该可后悔。
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from .. import config
from ..errors import AppError, ErrorCode
from .drafting import (
    draft_filename,
    draft_text,
    existing_corpus,
    find_duplicate,
    render_draft,
    score_segment,
    segments_from_turns,
)

#: 归档目录名（放在 _inbox 里，仍然不会被 loader 扫到）
TRASH_DIRNAME = "_trash"
#: 只接受"纯文件名 + .md"：不含路径分隔符、不含 ..、不含 Windows 非法字符
_SAFE_NAME = re.compile(r"^[^/\\:*?\"<>|\r\n]+\.md$")
_H1 = re.compile(r"^#\s+(.+)$", re.M)


def inbox_dir() -> Path:
    return Path(config.SKILL_DIR) / "_inbox"


def trash_dir() -> Path:
    return inbox_dir() / TRASH_DIRNAME


def _resolve(name: str) -> Path:
    """把请求里的名字解析成 **_inbox 内**的真实路径；不合法直接拒绝（防目录穿越）。"""
    if not name or not _SAFE_NAME.match(name) or ".." in name:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"非法草稿名：{name!r}（只允许 _inbox 下的 .md）")
    base = inbox_dir().resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise AppError(ErrorCode.VALIDATION_ERROR, "只能操作 _inbox 目录下的草稿")
    return path


def _source_of(name: str) -> str:
    """粗略来源（给页面打徽章用）：chat- 前缀 = 对话抽取；NN- 前缀 = 文档抽取。"""
    if name.startswith("chat-"):
        return "对话抽取"
    if re.match(r"^\d+-", name):
        return "文档抽取"
    return "手工/其它"


def _body_without_template(text: str) -> str:
    """去掉模板注释与"待提炼"骨架 —— 它们不是内容，会把查重算歪。"""
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return body.split("## 待提炼")[0]


def list_drafts() -> dict:
    """列出草稿区（直接读盘，**不走技能缓存**，所以永远是最新的）。"""
    base = inbox_dir()
    trash = trash_dir()
    drafts: list[dict] = []
    corpus = existing_corpus()
    if base.is_dir():
        for path in sorted(base.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
                stat = path.stat()
            except OSError:
                continue          # 读不了就跳过，不要让整个列表挂掉
            question = (_H1.search(text).group(1).strip() if _H1.search(text) else "")
            # 查重时把自己从语料里摘掉，否则会自己匹配自己
            others = {k: v for k, v in corpus.items() if k != f"draft:{path.name}"}
            dup = find_duplicate(question, _body_without_template(text), others)
            drafts.append({
                "name": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "source": _source_of(path.name),
                "question": question or path.name,
                "content": text,
                "duplicate": list(dup) if dup else None,
            })
    return {
        "drafts": drafts,
        "inbox": str(base),
        "trash_count": len(list(trash.glob("*.md"))) if trash.is_dir() else 0,
    }


def archive_draft(name: str) -> dict:
    """把草稿移进 ``_inbox/_trash/``（**不是真删**，可后悔）。"""
    path = _resolve(name)
    if not path.is_file():
        raise AppError(ErrorCode.NOT_FOUND, f"草稿不存在：{name}")
    trash = trash_dir()
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = trash / f"{stamp}-{name}"
    suffix = 1
    while target.exists():                      # 同一秒内多次移除也不互相覆盖
        target = trash / f"{stamp}-{suffix}-{name}"
        suffix += 1
    shutil.move(str(path), str(target))
    return {
        "archived": name,
        "moved_to": f"{TRASH_DIRNAME}/{target.name}",
        "trash_count": len(list(trash.glob("*.md"))),
    }


def _locate_turn(turns: list, turn_index: int, expected_user: str) -> int:
    """定位要沉淀的那一轮：**优先按提问文本找**，没有文本才退回索引。

    为什么优先按文本：页面上显示的可能只是完整历史的一部分（刷新过页面、或同一个
    session 用了很久），此时"页面第 N 轮"和"库里第 N 轮"根本不是同一轮 —— 这正是
    实测踩到的坑：按索引定位会对不上，于是报"对话记录已变化"。

    按文本定位既**不依赖页面状态**，又不会归档到错误的一轮；同一个问题问过多次时
    取**最近一次**（"沉淀刚才这条"的语义）。
    """
    def norm(text: str) -> str:
        return " ".join((text or "").split())

    wanted = norm(expected_user)
    if wanted:
        for index in range(len(turns), 0, -1):
            if norm(getattr(turns[index - 1], "user", "")) == wanted:
                return index
        raise AppError(
            ErrorCode.NOT_FOUND,
            "这个会话里找不到这条提问（页面显示的可能不是完整历史）。"
            "刷新页面后重试；若是刚编辑过的提问，重新发一次再沉淀。",
        )

    index = int(turn_index or 0)
    if not 1 <= index <= len(turns):
        raise AppError(ErrorCode.VALIDATION_ERROR,
                       f"轮次 {index} 超出范围（该会话共 {len(turns)} 轮）")
    return index


def create_from_chat(session_id: str, turn_index: int, expected_user: str = "") -> dict:
    """从某一轮所在的**事件片段**生成草稿（对话页「沉淀为经验」按钮）。

    两点刻意的设计：

    1. **不再用 ``is_candidate`` 过滤** —— 这是**人工显式信号**，优先级高于一切自动判断：
       人点了就写（评分与信号照样附在返回里，让人自己判断值不值得提升）。
    2. **仍然查重** —— 同一个坑点两次不该产生两份草稿；重复时返回已有条目，由页面提示。
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "缺少 session_id")

    from ..context.history import ChatStore      # 函数内导入：避免模块级循环依赖

    turns = ChatStore(config.DATA_DIR / "chat_history").load(session_id)
    if not turns:
        raise AppError(ErrorCode.NOT_FOUND, f"会话 {session_id} 没有对话记录")
    index = _locate_turn(turns, turn_index, expected_user)

    segment = next(
        (s for s in segments_from_turns(session_id, turns)
         if s["start"] <= index < s["start"] + len(s["turns"])),
        None,
    )
    if segment is None:                          # 兜底：退化成"只取这一轮"
        segment = {"session": session_id, "start": index, "turns": [turns[index - 1]]}

    item = score_segment(segment)
    summary = {
        "score": item["score"],
        "categories": item["categories"],
        "start": item["start"],
        "turns": item["turns"],
        "signals": {"symptom": item["symptom"], "action": item["action"], "verify": item["verify"]},
    }
    duplicate = find_duplicate(item["first_question"], draft_text(item), existing_corpus())
    if duplicate:
        return {"created": None, "duplicate": list(duplicate), **summary}

    inbox_dir().mkdir(parents=True, exist_ok=True)
    path = inbox_dir() / draft_filename(item)
    path.write_text(render_draft(item), encoding="utf-8")
    return {"created": path.name, "duplicate": None, **summary}
