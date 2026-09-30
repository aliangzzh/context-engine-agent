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
#: 三类信号 = 四段式的雏形（现象 → 动作 → 验证）。
#: **现象只在用户提问里找**：用户主动提出的问题才是真踩坑；动作/验证可以在任意位置。
_SYMPTOM = (
    "报错", "错误", "异常", "失败", "Error", "Exception", "Traceback", "不对", "不生效",
    "没生效", "无效", "认不出", "错在哪", "覆盖了", "丢了", "崩", "为什么",
)
_ACTION = (
    "修复", "改成", "换成", "加上", "删掉", "回滚", "重建", "降级", "隔离", "加锁",
    "重试", "定位", "排查", "覆盖", "改完", "补上", "拆分",
)
_VERIFY = (
    "验证", "测试", "跑一遍", "断言", "全绿", "复现", "仍然", "还是", "通过", "确认",
    "重建后", "再查", "对比",
)
#: 业务/闲聊词：命中就整段丢弃 —— 业务问答不是开发经验（实测里 12 轮的业务会话
#: 会靠"修复/重建"这类词蹭到高分，所以这里用"丢弃"而不是"扣分"）。
_OFFTOPIC = (
    "尺码", "洗护", "洗涤", "物流", "售后", "积分", "库存", "材质", "颜色", "天气",
    "气温", "几点", "你好", "您好", "谢谢", "hi", "hello", "你是谁",
)
#: 一个片段最多几轮；超了就断开（长片段容易"蹭分"）
MAX_SEGMENT_TURNS = 8
#: 默认只输出前 N 条（防 inbox 爆炸）
DEFAULT_TOP = 5
#: 候选的内容词被已有条目**覆盖率**超过这个值 → 算重复
DUP_COVERAGE = 0.7
#: 草稿里最多摘录多少字回答（素材，不是全文）
EXCERPT_LIMIT = 1200

_SCRUB = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{8,}"), r"\1***"),
    (re.compile(r"(?i)(api[_\-]?key\s*[=:]\s*)\S+"), r"\1***"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "***.***.***.***"),
)


def scrub(text: str) -> str:
    """脱敏：对话里可能带 key / Authorization 头 / 内网 IP，落盘前统一打码。"""
    out = text or ""
    for pattern, repl in _SCRUB:
        out = pattern.sub(repl, out)
    return out


def _hits(text: str, words) -> list[str]:
    return [w for w in words if w in text]


def segments_from_turns(session_id: str, turns: list) -> list[dict]:
    """把会话切成"事件片段"：遇到含现象词的**用户轮**就开一段。

    为什么不按会话切：一次排查通常跨好几轮（"为什么 X" → "试了 Y" → "原来 Z"），
    按会话切会把几个坑混成一条；按单轮切又会把一次排查切碎。
    """
    segments: list[dict] = []
    current: dict | None = None
    for index, turn in enumerate(turns, start=1):
        question = getattr(turn, "user", "") or ""
        if current is None or _hits(question, _SYMPTOM):
            if current is not None:
                segments.append(current)
            current = {"session": session_id, "start": index, "turns": []}
        current["turns"].append(turn)
        if len(current["turns"]) >= MAX_SEGMENT_TURNS:
            segments.append(current)
            current = None
    if current and current["turns"]:
        segments.append(current)
    return segments


def score_segment(segment: dict) -> dict:
    """给片段打分：三类信号是主体，首问/有实质结论加分，业务与超长减分。"""
    turns = segment["turns"]
    questions = " ".join(getattr(t, "user", "") or "" for t in turns)
    answers = " ".join(getattr(t, "assistant", "") or "" for t in turns)
    whole = f"{questions} {answers}"

    symptom = _hits(questions, _SYMPTOM)
    action = _hits(whole, _ACTION)
    verify = _hits(whole, _VERIFY)
    offtopic = _hits(whole, _OFFTOPIC)
    categories = sum(1 for group in (symptom, action, verify) if group)

    score = float(categories * 2)
    score += 1.0 if symptom else 0.0
    score += 1.0 if len(answers) > 400 else 0.0
    score -= 0.5 * max(0, len(turns) - MAX_SEGMENT_TURNS)

    return {
        "score": round(score, 1),
        "categories": categories,
        "symptom": symptom[:4],
        "action": action[:4],
        "verify": verify[:4],
        "offtopic": offtopic,
        "turns": len(turns),
        "start": segment["start"],
        "session": segment["session"],
        "first_question": (getattr(turns[0], "user", "") or "").strip(),
        "questions": [getattr(t, "user", "") or "" for t in turns],
        "answer": answers,
        "segment": segment,
    }


def is_candidate(item: dict) -> bool:
    """够不够格进草稿：现象出现在**用户提问**里 + 至少两类信号 + 不是业务/闲聊。"""
    return bool(item["symptom"]) and item["categories"] >= 2 and not item["offtopic"]


def find_duplicate(question: str, text: str, existing: dict[str, str]) -> tuple[str, float] | None:
    """查重：① 候选内容基本被已有条目覆盖 ② 问题本身被覆盖（同一个坑问了多次）。

    为什么用**覆盖率**而不是 Jaccard：Jaccard 会被"长度差"稀释 —— 候选几百字、
    已有技能一两千字时，即便讲的是同一件事也可能低于阈值（实测漏判过：同一个问题在
    4 个会话里各问一次，只抓到最后一对）。覆盖率是不对称的，正好表达
    "这条候选已经被覆盖了"。
    """
    from app.context.rerank import coverage

    best: tuple[str, float] | None = None
    for name, other in existing.items():
        if not (other or "").strip():
            continue
        score = max(coverage(text, other), coverage(question, other))
        if score >= DUP_COVERAGE and (best is None or score > best[1]):
            best = (name, round(score, 2))
    return best


def existing_corpus() -> dict[str, str]:
    """查重目标：正式技能（名字+描述+正文）与草稿区里的文件。"""
    corpus: dict[str, str] = {}
    for skill in get_skills(reload=True).skills:
        corpus[f"skill:{skill.name}"] = f"{skill.name} {skill.description} {skill.body}"
    if _inbox().is_dir():
        for path in sorted(_inbox().glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)   # 模板注释不是内容
            text = text.split("## 待提炼")[0]                      # 四段式骨架是模板
            corpus[f"draft:{path.name}"] = text
    return corpus


CHAT_DRAFT_TEMPLATE = """<!-- 草稿：由 scripts/collect_experience.py from-chat 从**对话历史**自动抽取。
     ⚠️ AI 抽取 · **未验证** —— 会话里的中间判断经常是错的（例如先误判成环境问题、
        后来才定位到真正原因）。人工过三问之后，再移到 skills/<kebab-case>/SKILL.md：
           ① 真踩过吗（能指出当时的报错/现象）？
           ② 验证指向哪个文件 / 哪条测试？
           ③ 和已有技能重复吗（重复就合并，不要新增）？

     来源会话：{session} · 起始轮次 {start} · 抽于 {today}
     信号：现象 {symptom} / 动作 {action} / 验证 {verify} · 打分 {score}（类别 {categories}/3）
-->

# {title}

## 问（用户原话）

{questions}

## 答（对话记录摘录 · 已脱敏）

{answer}

## 待提炼（四段式）

- **现象**：TODO（报错原文 / 现象 / 复现步骤）
- **根因**：TODO
- **修复**：TODO（文件:行号）
- **验证**：TODO（跑哪条命令 / 哪个测试）
"""


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
        slug = _BAD_NAME_CHARS.sub("-", item["first_question"])[:40].strip(" -") or "对话片段"
        out = _inbox() / f"chat-{item['session'][:14]}-{item['start']}-{slug}.md"
        # 文件名要短，但 H1 是给人读的 —— 别把问题截断成"…结果每"
        heading = item["first_question"] or "对话片段"
        out.write_text(
            CHAT_DRAFT_TEMPLATE.format(
                session=item["session"],
                start=item["start"],
                today=today,
                symptom=item["symptom"],
                action=item["action"],
                verify=item["verify"],
                score=item["score"],
                categories=item["categories"],
                title=heading,
                questions=scrub("\n".join(f"- {q}" for q in item["questions"] if q.strip())),
                answer=scrub(item["answer"][:EXCERPT_LIMIT]),
            ),
            encoding="utf-8",
        )
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
