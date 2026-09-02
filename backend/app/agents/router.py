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

_WEATHER = ("天气", "气温", "温度", "下雨", "weather", "晴", "冷", "热")
_TIME = ("几点", "时间", "现在", "time", "日期", "几号", "星期")
_CALC = ("计算",  "+", "-", "*", "/", "×", "÷", "等于", "=?")
_QA_DIRECT = ("你好", "嗨", "hi", "hello", "谢谢", "你是谁", "介绍")


def _looks_like_calc(text: str) -> bool:
    if "计算" in text:
        return True
    has_num = bool(re.search(r"\d", text))
    has_op = any(s in text for s in ("+", "-", "*", "/", "×", "÷"))
    return has_num and has_op


def route(user_input: str, kb_relevant: bool = False) -> list[str]:
    """Return the ordered list of agent steps, e.g. ``['retrieve']`` or
    ``['tool:calculator', 'retrieve']``."""
    text = user_input.lower()

    if _looks_like_calc(text):
        return ["tool:calculator"]
    if any(k in text for k in _WEATHER):
        return ["tool:get_weather"]
    if any(k in text for k in _TIME):
        return ["tool:current_time"]
    if any(k in text for k in _KB_KEYWORDS) or kb_relevant:
        return ["retrieve"]
    if any(k in text for k in _QA_DIRECT):
        return ["direct"]
    return ["direct"]
