"""从对话历史起草技能的**规则**（切片 / 打分 / 查重 / 渲染）。

为什么放在 app 层而不是 ``scripts/``：
**接口（对话页「沉淀为经验」按钮）与 CLI（``collect_experience from-chat``）必须用同一套规则** ——
否则同一个坑，按钮产出的草稿和命令行产出的草稿会不一样，查重也会互相看不见。
脚本现在只做参数解析与打印，规则全在这里。

三层信号的设计意图：**现象 → 动作 → 验证** 就是四段式（现象/根因/修复/验证）的雏形。
其中"现象"只在**用户提问**里找 —— 用户主动提出的问题才是真踩坑；动作与验证可以在任意位置。
"""
from __future__ import annotations

import re
from datetime import date

#: 现象词（只在用户提问里匹配）
_SYMPTOM = (
    "报错", "错误", "异常", "失败", "Error", "Exception", "Traceback", "不对", "不生效",
    "没生效", "无效", "认不出", "错在哪", "覆盖了", "丢了", "崩", "为什么",
)
#: 动作词（修复动作）
_ACTION = (
    "修复", "改成", "换成", "加上", "删掉", "回滚", "重建", "降级", "隔离", "加锁",
    "重试", "定位", "排查", "覆盖", "改完", "补上", "拆分",
)
#: 验证词（怎么证明修好了）
_VERIFY = (
    "验证", "测试", "跑一遍", "断言", "全绿", "复现", "仍然", "还是", "通过", "确认",
    "重建后", "再查", "对比",
)
#: 业务/闲聊词：命中就整段丢弃 —— 业务问答不是开发经验。
#: 用"丢弃"而不是"扣分"：实测里 12 轮的业务会话会靠"修复/重建"这类词蹭到高分。
_OFFTOPIC = (
    "尺码", "洗护", "洗涤", "物流", "售后", "积分", "库存", "材质", "颜色", "天气",
    "气温", "几点", "你好", "您好", "谢谢", "hi", "hello", "你是谁",
)
#: 一个片段最多几轮；超了就断开（长片段容易"蹭分"）
MAX_SEGMENT_TURNS = 8
#: 与已有技能/草稿的**内容词覆盖率**阈值，超过就算重复
DUP_COVERAGE = 0.7
#: 草稿里最多摘录多少字回答（素材，不是全文）
EXCERPT_LIMIT = 1200
#: 文件名里不允许出现的字符
_BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n]+')
#: 脱敏：key / Authorization 头 / 内网 IP
_SCRUB = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{8,}"), r"\1***"),
    # 值已经被上面打成 *** 时别再抹一遍（否则看不出"这原本是个 sk- key"）
    (re.compile(r"(?i)(api[_\-]?key\s*[=:]\s*)(?!\*)\S+"), r"\1***"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "***.***.***.***"),
)

CHAT_DRAFT_TEMPLATE = """<!-- 草稿：由 collect_experience / 对话页「沉淀为经验」从**对话历史**自动抽取。
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
    """给片段打分：三类信号是主体，首问/有实质结论加分，超长减分。"""
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
    from ..context.rerank import coverage

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
    from . import get_skills                       # 函数内导入：避免 app.skills 循环导入
    from .drafts import inbox_dir

    corpus: dict[str, str] = {}
    for skill in get_skills(reload=True).skills:
        corpus[f"skill:{skill.name}"] = f"{skill.name} {skill.description} {skill.body}"
    if inbox_dir().is_dir():
        for path in sorted(inbox_dir().glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)   # 模板注释不是内容
            text = text.split("## 待提炼")[0]                      # 四段式骨架是模板
            corpus[f"draft:{path.name}"] = text
    return corpus


def draft_text(item: dict) -> str:
    """查重用的"候选正文"（与写入文件的内容口径一致）。"""
    return f"{item['first_question']} {item['answer'][:400]}"


def draft_slug(item: dict) -> str:
    """文件名用的 slug（短、去掉非法字符）；H1 用完整问题，不截断。"""
    slug = _BAD_NAME_CHARS.sub("-", item["first_question"])[:40].strip(" -")
    return slug or "对话片段"


def draft_filename(item: dict) -> str:
    return f"chat-{item['session'][:14]}-{item['start']}-{draft_slug(item)}.md"


def render_draft(item: dict, *, today: str | None = None) -> str:
    """渲染草稿内容（CLI 与接口共用，保证两种入口产出的文件完全同构）。"""
    return CHAT_DRAFT_TEMPLATE.format(
        session=item["session"],
        start=item["start"],
        today=today or date.today().isoformat(),
        symptom=item["symptom"],
        action=item["action"],
        verify=item["verify"],
        score=item["score"],
        categories=item["categories"],
        title=item["first_question"] or "对话片段",
        questions=scrub("\n".join(f"- {q}" for q in item["questions"] if q.strip())),
        answer=scrub(item["answer"][:EXCERPT_LIMIT]),
    )
