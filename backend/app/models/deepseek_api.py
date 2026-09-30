"""DeepSeek 对话后端（OpenAI 兼容的 HTTP 接口）。

为什么**手写 requests** 而不引 ``openai`` SDK：

* 核心依赖里已经有 ``requests``（零新增依赖，CI 装 ``requirements.txt`` 就有）；
* 只用到两个形态（普通 / 流式）的同一个端点，协议很薄，手写反而看得清
  —— 和 ``mcp_server.py`` 手写 JSON-RPC 是同一个取舍。

官方文档（https://api-docs.deepseek.com/）：::

    base_url = https://api.deepseek.com
    POST /chat/completions
    Authorization: Bearer $DEEPSEEK_API_KEY
    model = deepseek-flash | deepseek-v4-pro

失败策略：**构造时**缺 key 直接抛（由 ``models.get_model_backend`` 记降级原因并退回
fake）；**运行期** HTTP/结构错误抛 ``RuntimeError``，由上层转成 ``502xx`` 上游错误码，
不静默吞掉。
"""
from __future__ import annotations

import json
from typing import Iterable

from .. import config
from .base import ModelBackend

#: 单次请求超时（秒）。真模型偶尔慢，但 60s 还没响应就该报错了。
TIMEOUT = 60


class DeepSeekApiModel(ModelBackend):
    name = "deepseek_api"

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.3,
        base_url: str | None = None,
    ):
        self._key = (config.DEEPSEEK_API_KEY or "").strip()
        if not self._key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY（在 backend/.env 里配置）")
        self._model = model or config.DEEPSEEK_CHAT_MODEL
        self._temperature = temperature
        self._base = (base_url or config.DEEPSEEK_BASE_URL).rstrip("/")

    # -- 请求构造 -------------------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._key}",
        }

    def _payload(self, messages: list[dict], *, stream: bool) -> dict:
        return {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "temperature": self._temperature,
        }

    def _endpoint(self) -> str:
        return f"{self._base}/chat/completions"

    @staticmethod
    def _check(resp) -> None:
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek 返回 HTTP {resp.status_code}：{str(resp.text)[:200]}")

    # -- 接口 -----------------------------------------------------------------------
    def generate(self, messages: list[dict]) -> str:
        import requests

        resp = requests.post(
            self._endpoint(),
            headers=self._headers(),
            json=self._payload(messages, stream=False),
            timeout=TIMEOUT,
        )
        self._check(resp)
        data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"DeepSeek 响应结构异常：{str(data)[:200]}") from exc

    def stream(self, messages: list[dict]) -> Iterable[str]:
        import requests

        with requests.post(
            self._endpoint(),
            headers=self._headers(),
            json=self._payload(messages, stream=True),
            timeout=TIMEOUT,
            stream=True,
        ) as resp:
            self._check(resp)
            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore").strip() if isinstance(raw, bytes) else str(raw).strip()
                if not line.startswith("data:"):
                    continue           # 事件名/心跳行：跳过
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0].get("delta") or {}
                except Exception:
                    continue           # 半包/非 JSON 行：跳过，不中断整条流
                piece = delta.get("content")
                if piece:
                    yield str(piece)
