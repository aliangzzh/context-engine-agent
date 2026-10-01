"""Agent tools: real free API + local functions, with graceful offline fallback.

Tools are plain functions wrapped with a name/description so the orchestrator's
tool agent can call them, and so an interviewer sees a standard function-calling
interface. Network failures degrade to deterministic text rather than crashing
the agent loop.

* ``extract_args`` 负责"从自然语言里抽参数"——这是 function calling 的关键一步，
  也是上一版最弱的地方（当时把整句用户输入当参数传进去，工具必然算错）。
* ``@retry`` 用在真正会失败的网络上（Open-Meteo），``@timed`` 记录每个工具的耗时，
  两者都是带参数的装饰器。
"""
from __future__ import annotations

import ast
import operator
import re
from datetime import datetime, timezone
from typing import Callable

import requests

from .. import config
from ..decorators import retry, timed
from ..skills import get_skills, select_skills

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


def _weather_online(city: str) -> str:
    """真正打网络的实现（失败直接抛，交给 @retry 重试）。"""
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


@timed("tool.get_weather")
def get_weather(city: str) -> str:
    city = (city or "").strip()
    if not city:
        return "请提供城市名"
    try:
        # 外部 API 抖动是常态：重试 3 次（0.3s -> 0.6s 退避）
        return _retry_weather(city)
    except Exception:
        return f"（离线/网络不可用）无法实时查询「{city}」天气"


# 装饰器包在真正的网络调用上，才能"重试失败"而不是"重试一个已经兜底的结果"
_retry_weather = retry(times=3, delay=0.3, backoff=2.0)(_weather_online)


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


@timed("tool.calculator")
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


@timed("tool.current_time")
def current_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --- 开发经验技能检索（skills/ 目录，规范见 skills/README.md） -------------------------
@timed("tool.search_skill")
def search_skill(query: str) -> str:
    """按关键词检索技能库，返回命中技能的规则正文。

    为什么单独做成一个工具、而不是把技能塞进业务知识库：两者是**两套语料**——
    混在一个索引里会互相挤掉 top-k，还会共用缓存 key（见 docs/skill-plan.md §2）。
    工具边界清楚，也方便外部编码 Agent 通过 MCP 直接调用。
    """
    query = (query or "").strip()
    if not query:
        return "请给出要检索的关键词（例如：工具参数怎么抽）"
    if not config.SKILL_ENABLED:
        return "技能库当前已关闭（SKILL_ENABLED=0）"

    loaded = get_skills()
    if not loaded.skills:
        return "技能库是空的（skills/ 目录下还没有技能）"

    # 选技能的顺序固定在 skills/store.select_skills 里（精准门 → 语料检索 → 相关性门控），
    # 工具与 Agent 的 skill 节点共用同一套判断，避免两边行为漂移。
    matches, chunks = select_skills(query, loaded.skills)
    if chunks:
        return "\n\n".join(
            f"【技能 {str(c.source).replace('skill:', '')}】相关度 {c.score}"
            f"｜来源：{(c.meta or {}).get('path', '')}\n{c.text}"
            for c in chunks
        )

    # 语料还没同步出来（首次 clone）/ 门控太严时，退回关键词匹配的正文
    if matches:
        return "\n\n".join(
            f"【技能 {m.skill.name}】命中：{'、'.join(m.hits)}｜来源：{m.skill.path}\n"
            f"{m.skill.description}\n{m.skill.body[:800]}"
            for m in matches
        )

    # 没有就如实说没有（不硬凑一条），顺带提示有文件被跳过 —— 写错的技能要能被发现
    hint = f"（另有 {len(loaded.skipped)} 个技能文件格式有问题被跳过）" if loaded.skipped else ""
    return f"技能库中没有与「{query}」相关的经验{hint}"


# --- 参数抽取（自然语言 -> 工具参数） -------------------------------------------------
_CN_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
#: 全角括号/运算符归一化：不还原的话「（18+6）乘以3」会被抽成 "18+6"，算出 24（错答案）
_FULLWIDTH = str.maketrans({
    "（": "(", "）": ")", "［": "[", "］": "]",
    "＋": "+", "－": "-", "＊": "*", "／": "/", "％": "%", "．": ".",
    "，": ",", "、": ",", "。": ".", "：": ":",
})
_CN_OPS = {"加上": "+", "加": "+", "减去": "-", "减": "-", "乘以": "*", "乘": "*",
           "除以": "/", "除": "/", "的平方": "**2"}
_EXPR_RUN_RE = re.compile(r"[0-9\(\)\.\s\+\-\*/%]+")
_EXPR_LEAD = re.compile(r"^[^\d\(]+")
_EXPR_TAIL = re.compile(r"[^\d\)]+$")
_CITY_RE = re.compile(
    r"([\u4e00-\u9fff]{2,8}?)(?:今天|明天|后天|现在)?(?:的)?"
    r"(?:会不会|会|要|可能)?"
    r"(?:天气|气温|温度|多少度|几度|下雨|下雪|冷不冷|热不热|冷吗|热吗)"
)
_EN_CITY_RE = re.compile(r"(?:weather|temperature)\s+(?:in|of|at)?\s*([A-Za-z][A-Za-z\s\-]{1,20})", re.I)
_WEATHER_NOISE = re.compile(
    r"(请问|帮我|查一下|查询|看一下|告诉我|今天|明天|后天|现在|的|天气|气温|温度|怎么样|如何|怎样|"
    r"多少度|几度|下雨|下雪|冷不冷|热不热|会|要|呢|吗|？|\?|，|,|。|！|!)"
)
_GREETING = re.compile(r"(你好|您好|谢谢|哈喽|hi|hello|在吗)", re.I)
_PLACE_TAIL = re.compile(r"(市|县|区|省|州|国|镇|乡)$")
#: 兜底路径：从「深圳明天会下雨吗」里截到第一个时间/体感/疑问词之前，取「深圳」。
#: 旧版是"逐个删噪声词再拼回去"，「会」没在噪声表里就留下「深圳会」这种脏城市名。
_WEATHER_HEAD = re.compile(
    r"(今天|明天|后天|现在|会不会|会|要|可能|的|天气|气温|温度|多少度|几度|下雨|下雪|"
    r"冷不冷|热不热|冷|热|暖和|呢|吗|？|\?|，|,|。|！|!)"
)
_QUERY_PREFIX = re.compile(r"^(请问|麻烦|帮我|帮忙|我想|我要|想知道|查一下|查询|看一下|告诉我)+")
#: 兜底抽地名时排除"动宾短语残渣"：「帮我查一下温度」截出来是「查一下」，不是城市
_NOT_PLACE = re.compile(r"(查|看|告|诉|知|道|问|算|写|怎|么|样)")


def _extract_expression(text: str) -> str:
    """从「12乘34加5等于多少」里抽出可计算的表达式。"""
    s = (text or "").translate(_CN_DIGITS).translate(_FULLWIDTH)
    for cn, op in sorted(_CN_OPS.items(), key=lambda kv: -len(kv[0])):
        s = s.replace(cn, op)

    candidates = []
    for run in _EXPR_RUN_RE.findall(s):
        expr = _EXPR_TAIL.sub("", _EXPR_LEAD.sub("", run.strip())).strip()
        # 必须同时含数字和运算符，否则「170」这种纯数字不该被当算式
        if re.search(r"\d", expr) and re.search(r"[\+\-\*/%]", expr):
            candidates.append(expr)
    if not candidates:
        return ""
    expr = max(candidates, key=len)
    # 括号不配平就直接放弃，别把非法表达式丢给计算器
    return expr if expr.count("(") == expr.count(")") else ""


def _extract_city(text: str) -> str:
    """从「北京今天天气怎么样」里抽出「北京」。"""
    s = (text or "").strip()
    for pattern in (_CITY_RE, _EN_CITY_RE):
        m = pattern.search(s)
        if m:
            city = _WEATHER_NOISE.sub("", m.group(1)).strip()
            if city:
                return city
    # 兜底：截到第一个时间/体感/疑问词之前，只接受"像地名"的短串（带行政区后缀，且不是寒暄）
    fallback = _QUERY_PREFIX.sub("", s)
    fallback = _WEATHER_HEAD.split(fallback)[0].strip()
    if _GREETING.search(fallback) or _NOT_PLACE.search(fallback) or not (2 <= len(fallback) <= 6):
        return ""
    if _PLACE_TAIL.search(fallback) or re.fullmatch(r"[\u4e00-\u9fff]{2,6}", fallback):
        return fallback
    return ""


def extract_args(name: str, user_input: str) -> dict:
    """自然语言 -> 工具参数（function calling 里的 arguments 那一步）。

    抽不出来就返回空 dict，由调用方给出"请补充参数"的提示，而不是把整句话
    塞进参数里算出错误结果（上一版就是这么错的）。
    """
    if name == "get_weather":
        city = _extract_city(user_input)
        return {"city": city} if city else {}
    if name == "calculator":
        expr = _extract_expression(user_input)
        return {"expression": expr} if expr else {}
    if name == "search_skill":
        # 检索类工具是"整句就是 query"的例外：这里要的正是用户原话（其它工具都不行）
        text = (user_input or "").strip()
        return {"query": text} if text else {}
    return {}


TOOLS: dict[str, Tool] = {}


def _register(name: str, desc: str, params: dict):
    f = {"get_weather": get_weather, "calculator": calculator, "current_time": current_time,
         "search_skill": search_skill}[name]
    TOOLS[name] = Tool(name, desc, f, params)


_register("get_weather", "查询指定城市的当前天气", {"city": "城市名"})
_register("calculator", "计算一个数学表达式", {"expression": "数学算式，如 3*4+2"})
_register("current_time", "获取当前时间", {})
_register("search_skill", "检索开发经验技能库（踩过的坑 / 最佳实践），返回技能规则正文",
          {"query": "要检索的关键词或问题"})


def get_tool(name: str) -> Tool | None:
    return TOOLS.get(name)


def tool_descriptions() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "params": t.params}
        for t in TOOLS.values()
    ]
