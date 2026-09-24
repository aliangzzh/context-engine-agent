"""Intent router: decides which sub-agents should collaborate on a request.

Rule-based by default (offline, deterministic). When a real model backend is
available the same interface can be backed by an LLM planner; the system design
is unchanged either way.
"""
from __future__ import annotations

import re

_KB_KEYWORDS = (
    "尺码", "体重", "身高", "洗涤", "保养", "颜色", "搭配", "面料", "材质",
    "洗护", "推荐", "知识库", "资料", "文档", "库", "衣服", "牛仔", "毛衣",
)

_WEATHER = ("天气", "气温", "温度", "多少度", "几度", "下雨", "下雪", "weather", "晴", "冷", "热")
_TIME = ("几点", "时间", "现在", "time", "日期", "几号", "星期")

#: 中文运算符也要能被认成算式：「12乘34加5等于多少」在旧版走不到计算器。
#: 必须夹在数字之间才算（否则「加绒牛仔」的「加」会误判成计算）。
_CN_CALC_RE = re.compile(r"\d\s*(?:乘以|乘|加上|加|减去|减|除以|除|×|÷)\s*[\(（]?\s*\d")


def _looks_like_calc(text: str) -> bool:
    if "计算" in text or "算一下" in text or "算下" in text:
        return True
    if _CN_CALC_RE.search(text):
        return True
    has_num = bool(re.search(r"\d", text))
    has_op = any(s in text for s in ("+", "-", "*", "/", "×", "÷"))
    return has_num and has_op


def route(user_input: str, kb_relevant: bool = False) -> list[str]:
    """Return the ordered list of agent steps, e.g. ``['retrieve']`` or
    ``['tool:calculator', 'retrieve']``.

    一句话里可能有多个意图（「上海天气怎么样？另外帮我算一下 8*7」），旧版
    命中第一个就 return，会漏掉另一个工具；现在把所有命中的能力**全部收集**，
    只有在没有工具意图时才退化为 检索/直接作答。
    """
    text = user_input.lower()

    steps: list[str] = []
    if _looks_like_calc(text):
        steps.append("tool:calculator")
    if any(k in text for k in _WEATHER):
        steps.append("tool:get_weather")
    if any(k in text for k in _TIME):
        steps.append("tool:current_time")

    wants_kb = any(k in text for k in _KB_KEYWORDS) or kb_relevant
    if not steps:
        return ["retrieve"] if wants_kb else ["direct"]
    if wants_kb:
        # 工具 + 知识库混合意图：先取事实，再检索补充
        steps.append("retrieve")
    return steps
