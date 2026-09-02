"""Agent tools: real free API + local functions, with graceful offline fallback.

Tools are plain functions wrapped with a name/description so the orchestrator's
tool agent can call them, and so an interviewer sees a standard function-calling
interface. Network failures degrade to deterministic text rather than crashing
the agent loop.
"""
from __future__ import annotations

import ast
import math
import operator
from datetime import datetime, timezone
from typing import Callable

import requests

TIMEOUT = 8


class Tool:
    def __init__(self, name: str, description: str, func: Callable[..., str], params: dict):
        self.name = name
        self.description = description
        self.func = func
        self.params = params

    def run(self, **kwargs) -> str:
        try:
            return str(self.func(**kwargs))
        except Exception as e:  # never let a tool crash the agent
            return f"工具执行出错：{e}"


# --- Weather (Open-Meteo, free, no key) ----------------------------------------
_WMO = {
    0: "晴", 1: "基本晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪", 80: "阵雨",
    95: "雷雨",
}


def get_weather(city: str) -> str:
    city = (city or "").strip()
    if not city:
        return "请提供城市名"
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh"},
            timeout=TIMEOUT,
        ).json()
        results = geo.get("results") or []
        if not results:
            return f"未找到城市「{city}」的坐标"
        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]
        wx = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=TIMEOUT,
        ).json()
        cur = wx["current"]
        code = cur.get("weather_code", 0)
        desc = _WMO.get(code, "未知")
        return (
            f"{loc.get('name', city)}：{desc}，当前温度 {cur['temperature_2m']}°C，"
            f"风速 {cur['wind_speed_10m']} km/h"
        )
    except Exception:
        return f"（离线/网络不可用）无法实时查询「{city}」天气"


# --- Safe calculator --------------------------------------------------------------
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_eval(node.operand)
    raise ValueError("不支持的表达式")


def calculator(expression: str) -> str:
    expr = (expression or "").replace("×", "*").replace("÷", "/").strip()
    if not expr:
        return "请输入算式"
    try:
        val = _safe_eval(ast.parse(expr, mode="eval").body)
    except Exception:
        return f"无法计算：{expression}"
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(round(val, 6))


def current_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


TOOLS: dict[str, Tool] = {}


def _register(name: str, desc: str, params: dict):
    f = {"get_weather": get_weather, "calculator": calculator, "current_time": current_time}[name]
    TOOLS[name] = Tool(name, desc, f, params)


_register("get_weather", "查询指定城市的当前天气", {"city": "城市名"})
_register("calculator", "计算一个数学表达式", {"expression": "数学算式，如 3*4+2"})
_register("current_time", "获取当前时间", {})


def get_tool(name: str) -> Tool | None:
    return TOOLS.get(name)


def tool_descriptions() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "params": t.params}
        for t in TOOLS.values()
    ]
