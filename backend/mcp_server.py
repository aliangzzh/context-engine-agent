"""最小 MCP Server：把项目里已有的工具，通过 MCP 协议（stdio）暴露出去。

MCP = Model Context Protocol（Anthropic 2024-11 开源），
本质是 **JSON-RPC 2.0 over stdio**：一行一个 JSON 消息，请求有 id，通知没有 id。

为什么手写而不用官方 ``mcp`` SDK：
* 零依赖，clone 下来就能跑；
* 能看清协议本身（initialize / tools/list / tools/call 三个方法而已）。

★ 它不重新实现任何工具 —— 工具定义和执行都复用 ``app/agents/tools.py``。
"""

from __future__ import annotations

import json
import sys
from typing import Any

from app.agents.tools import TOOLS, get_tool

SERVER_NAME = "context-engine-tools"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

#: MCP 的工具参数需要 JSON Schema（带类型），
#: 而项目里的 ``Tool.params`` 只有人类可读的说明（如 {"city": "城市名"}），
#: 所以这里显式补一份 schema。工具的实现仍然复用 tools.py。
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_weather": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名"}},
        "required": ["city"],
    },
    "calculator": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学算式，如 3*4+2"}
        },
        "required": ["expression"],
    },
    "current_time": {"type": "object", "properties": {}},
}


def tools_list() -> list[dict[str, Any]]:
    """把项目里的 ``TOOLS`` 转成 MCP 的工具定义列表。"""
    out: list[dict[str, Any]] = []
    for name, tool in TOOLS.items():
        out.append(
            {
                "name": name,
                "description": tool.description,
                "inputSchema": _TOOL_SCHEMAS.get(
                    name, {"type": "object", "properties": {}}
                ),
            }
        )
    return out


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """执行工具 —— ★ 直接复用项目里已有的 ``Tool.run()``。"""
    tool = get_tool(name)
    if tool is None:
        return {
            "content": [{"type": "text", "text": f"未知工具：{name}"}],
            "isError": True,
        }
    text = tool.run(**arguments)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 消息；通知（没有 id）返回 None，不回复。"""
    method = msg.get("method")
    req_id = msg.get("id")

    if req_id is None:  # 通知，例如 notifications/initialized
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list()}}

    if method == "tools/call":
        params = msg.get("params") or {}
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": call_tool(params.get("name", ""), params.get("arguments") or {}),
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    """stdio 主循环：读一行 JSON → 处理 → 回一行 JSON。"""
    for raw in sys.stdin:
        # 容忍 BOM：PowerShell 管道喂进来的【第一行】会带 UTF-8 BOM（EF BB BF），
        # 不剥掉的话 json.loads 会失败，表现为"第一行莫名消失"。
        line = raw.lstrip("\ufeff").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
