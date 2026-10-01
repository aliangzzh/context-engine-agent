"""开发经验归档脚本（零依赖：stdlib + 项目内的 ``app.skills``）。

在 ``backend/`` 下执行：

    python -m scripts.collect_experience draft      # 从 docs/ 抽"踩坑草稿"到 skills/_inbox/
    python -m scripts.collect_experience check      # 校验 skills/*/SKILL.md（可挂 CI，不合规 exit 1）
    python -m scripts.collect_experience sync       # 把 skills/ 同步进检索语料（按 md5 幂等）
    python -m scripts.collect_experience sync --force

为什么 ``draft`` 只产出**草稿**、不直接写成正式技能：
从散文里自动抽出来的"现象 / 根因 / 修复 / 验证"必然是半成品（缺行号、缺验证命令）。
自动归档的价值是**不漏素材**，不是**替人下结论** —— 所以草稿落在 ``skills/_inbox/``，
人工补齐后再移进 ``skills/<kebab-case>/SKILL.md``。

三个子命令对应的是"经验复用"闭环的前半段：**归档 → 结构化 → 入库**。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402
from app.skills import corpus_status, ensure_synced, get_skills  # noqa: E402

def _inbox() -> Path:
    """草稿区目录（读 config 而不是模块常量，方便测试与换目录）。"""
    return Path(config.SKILL_DIR) / "_inbox"


DEFAULT_SOURCES = ("docs/ai-assisted.md", "docs/code-review.md")

_H2 = re.compile(r"^##\s+(.*)$")
_ITEM = re.compile(r"^(\d+)\.\s+\*\*(.+?)\*\*[：:]\s*(.*)$")
_BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n]+')

DRAFT_TEMPLATE = """<!-- 草稿：由 scripts/collect_experience.py 从 {source} 自动抽取。
     请人工补全所有 TODO、删掉本注释，再移到 skills/<kebab-case-name>/SKILL.md -->

---
name: TODO-改成-kebab-case-且与目录名一致
description: TODO 一句话说清什么时候该用它（这是触发匹配的主要依据）
tags: []
trigger: []
stack: []
status: active
version: 1
updated: {today}
---

# {title}

## 现象
TODO 贴真实现象 / 报错 / 复现步骤

## 根因
{root_cause}

## 修复
TODO 改了什么（写清 文件:行号）

## 验证
TODO 跑哪条命令 / 哪个测试

## 自查
- TODO 看到什么就说明正在犯这个错
"""


def collect_items(text: str) -> list[dict]:
    """抽取 ``N. **标题**：解释...`` 形式的条目（本项目文档里就是踩坑清单这种写法）。

    只在遇到标题行时切换小节；空行结束当前条目 —— 避免把下一节的散文粘到上一条上。
    """
    section = ""
    items: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            h2 = _H2.match(line)
            if h2:
                section = h2.group(1).strip()
            current = None
            continue
        if not line:
            current = None
            continue
        matched = _ITEM.match(line)
        if matched:
            current = {
                "section": section,
                "index": int(matched.group(1)),
                "title": matched.group(2).strip(),
                "body": matched.group(3).strip(),
            }
            items.append(current)
            continue
        if current is not None:
            current["body"] = f"{current['body']}\n{line}"
    return items


def _draft_name(index: int, title: str) -> str:
    safe = _BAD_NAME_CHARS.sub("-", title).strip(" -") or f"item-{index}"
    return f"{index:02d}-{safe}.md"


def cmd_draft(args: argparse.Namespace) -> int:
    sources = args.source or [str(PROJECT_DIR / s) for s in DEFAULT_SOURCES]
    _inbox().mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    for src in sources:
        path = Path(src)
        if not path.exists():
            print(f"  ! 跳过（不存在）：{path}")
            continue
        items = collect_items(path.read_text(encoding="utf-8"))
        for item in items:
            out = _inbox() / _draft_name(item["index"], item["title"])
            if out.exists() and not args.force:
                skipped += 1
                continue
            out.write_text(
                DRAFT_TEMPLATE.format(
                    source=path.name,
                    today=date.today().isoformat(),
                    title=item["title"],
                    root_cause=item["body"] or "TODO",
                ),
                encoding="utf-8",
            )
            written += 1
        print(f"  · {path.name}：抽出 {len(items)} 条")
    print(f"\n草稿目录：{_inbox()}")
    print(f"新写入 {written} 份，已存在跳过 {skipped} 份（--force 可覆盖）")
    print("下一步：人工补全 TODO → 移到 skills/<name>/SKILL.md → 跑 check 与 sync")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    loaded = get_skills(reload=True)
    print(f"技能目录：{config.SKILL_DIR}")
    for skill in loaded.skills:
        warn = ""
        if not skill.tags and not skill.trigger:
            warn = "  [警告] 既没有 tags 也没有 trigger：只能靠语料检索命中"
        print(f"  [OK]   {skill.name:32s} v{skill.version}{warn}")
    for bad in loaded.skipped:
        print(f"  [跳过] {bad['path']}\n         原因：{bad['reason']}")
    drafts = sorted(_inbox().glob("*.md")) if _inbox().is_dir() else []
    if drafts:
        print(f"\n提示：{_inbox()} 还有 {len(drafts)} 份草稿待补全")
    print(f"\n合规 {len(loaded.skills)} 个，跳过 {len(loaded.skipped)} 个")
    return 1 if loaded.skipped else 0


def cmd_sync(args: argparse.Namespace) -> int:
    loaded = get_skills(reload=True)
    if loaded.skipped:
        print("注意：以下技能因格式问题未进入语料（先跑 check 修掉）：")
        for bad in loaded.skipped:
            print(f"  - {bad['path']}：{bad['reason']}")
    summary = ensure_synced(loaded.skills, force=args.force)
    if summary["rebuilt"]:
        print("已重建技能语料：")
        print(f"  变化：{summary['changed'] or '无'}    移除：{summary['removed'] or '无'}")
    else:
        print("技能语料已是最新（md5 清单一致），无需重建")
    info = corpus_status(loaded.skills)
    print(f"  技能数 {info['loaded']}    语料分块 {info['chunks']}    检索后端 {info['backend']}")
    print(f"  语料文件 {info['kb_path']}")
    return 0


# --- 从对话历史起草（from-chat）------------------------------------------------------
# 起草规则（切片 / 打分 / 查重 / 渲染）统一放在 ``app/skills/drafting.py``：
# **对话页的「沉淀为经验」按钮和这个 CLI 必须用同一套规则**，否则两个入口产出的草稿
# 会不一样、查重也互相看不见。这里只做名字转发，脚本本身只管参数与打印。
from app.skills.drafting import (          # noqa: E402
    draft_filename, existing_corpus, find_duplicate, is_candidate,
    render_draft, score_segment, segments_from_turns,
)

#: 默认只输出前 N 条（防 inbox 爆炸）
DEFAULT_TOP = 5


def cmd_from_chat(args: argparse.Namespace) -> int:
    """从对话历史挑候选 → 生成"素材级"草稿。

    默认**只列候选、不写文件**（dry-run）：AI 只提议，落盘由人决定。
    """
    from app.context.history import ChatStore

    store = ChatStore(config.DATA_DIR / "chat_history")
    session_ids = [args.session] if args.session else store.sessions()
    if not session_ids:
        print("对话历史里没有任何会话（先聊几句再回来）。")
        return 1

    total_turns = 0
    scored: list[dict] = []
    for session_id in session_ids:
        turns = store.load(session_id)
        total_turns += len(turns)
        for segment in segments_from_turns(session_id, turns):
            scored.append(score_segment(segment))

    # 筛选：现象必须在**用户提问**里出现、至少两类信号、且不是业务/闲聊会话
    kept = [s for s in scored if is_candidate(s)]
    kept.sort(key=lambda s: (-s["score"], s["session"], s["start"]))
    print(f"扫描 {len(session_ids)} 个会话 / {total_turns} 轮对话")
    print(f"切出 {len(scored)} 个片段，通过筛选 {len(kept)} 个"
          f"（丢弃 {len(scored) - len(kept)}：缺现象词 / 信号不足 / 业务闲聊）\n")
    if not kept:
        print("没有值得沉淀的片段。")
        return 0

    corpus = existing_corpus()
    picked: dict[str, str] = {}

    # 去重分两层：① 与已有技能/草稿比（corpus）② **本批候选之间**也比
    # （实测：同一个坑在 4 个会话里各问过一次，不去重就会写出 4 份一样的草稿）
    for item in kept:
        text = f"{item['first_question']} {item['answer'][:400]}"
        dup = find_duplicate(item["first_question"], text, {**corpus, **picked})
        item["duplicate"] = dup
        if dup is None:
            picked[f"本批#{len(picked) + 1}"] = text

    top = kept[: max(1, args.top)]
    print(f"{'分数':<6}{'类别':<6}{'轮数':<6}{'会话':<18}首问")
    for item in top:
        dup = item["duplicate"]
        mark = f"   ⚠ 与 {dup[0]} 相似 {dup[1]}" if dup else ""
        print(f"{item['score']:<6}{str(item['categories']) + '/3':<6}{item['turns']:<6}"
              f"{item['session'][:16]:<18}{item['first_question'][:30]}{mark}")
        if args.verbose:
            print(f"        现象 {item['symptom']} / 动作 {item['action']} / 验证 {item['verify']}")

    if not args.write:
        print("\n（dry-run：没有写文件。确认后加 --write 落到 skills/_inbox/）")
        return 0

    _inbox().mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    written = skipped_dup = 0
    for item in top:
        dup = item["duplicate"]
        if dup and not args.force:
            print(f"  跳过（重复 {dup[0]} 相似 {dup[1]}）：{item['first_question'][:30]}")
            skipped_dup += 1
            continue
        out = _inbox() / draft_filename(item)      # 命名与接口共用，保证两个入口同构
        out.write_text(render_draft(item, today=today), encoding="utf-8")
        written += 1
        print(f"  写入 {out.name}")
    print(f"\n共写入 {written} 份草稿，跳过重复 {skipped_dup} 份；目录：{_inbox()}")
    print("下一步：人工过三问 → 移到 skills/<name>/SKILL.md → check → sync")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="开发经验归档 / 校验 / 入库")
    sub = parser.add_subparsers(dest="command", required=True)

    p_draft = sub.add_parser("draft", help="从文档抽踩坑草稿到 skills/_inbox/")
    p_draft.add_argument("--source", action="append", help="源文档（可多次；默认 docs/ai-assisted.md 等）")
    p_draft.add_argument("--force", action="store_true", help="覆盖已存在的草稿")
    p_draft.set_defaults(func=cmd_draft)

    p_check = sub.add_parser("check", help="校验 skills/ 里的技能是否合规")
    p_check.set_defaults(func=cmd_check)

    p_chat = sub.add_parser("from-chat", help="从对话历史挑候选 → 草稿（默认 dry-run，只列不写）")
    p_chat.add_argument("--session", help="只处理某个会话 id（默认扫描全部会话）")
    p_chat.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"最多取前 N 条（默认 {DEFAULT_TOP}）")
    p_chat.add_argument("--write", action="store_true", help="真的写入 skills/_inbox/（不加则只列候选）")
    p_chat.add_argument("--force", action="store_true", help="即使疑似重复也写")
    p_chat.add_argument("--verbose", action="store_true", help="打印命中的信号词")
    p_chat.set_defaults(func=cmd_from_chat)

    p_sync = sub.add_parser("sync", help="把 skills/ 同步进技能检索语料")
    p_sync.add_argument("--force", action="store_true", help="忽略 md5 清单，强制重建")
    p_sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
