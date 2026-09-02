"""Qwen (Tongyi) chat model via DashScope, through LangChain."""
from __future__ import annotations

from typing import Iterable

from .. import config
from .base import ModelBackend


class QwenApiModel(ModelBackend):
    name = "qwen_api"

    def __init__(self, model: str | None = None, temperature: float = 0.3):
        from langchain_community.chat_models.tongyi import ChatTongyi
        self._client = ChatTongyi(model=model or config.QWEN_CHAT_MODEL, temperature=temperature)

    def generate(self, messages: list[dict]) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        lc = []
        for m in messages:
            if m["role"] == "user":
                lc.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                lc.append(AIMessage(content=m["content"]))
            else:
                lc.append(SystemMessage(content=m["content"]))
        res = self._client.invoke(lc)
        return str(res.content)

    def stream(self, messages: list[dict]) -> Iterable[str]:
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        lc = []
        for m in messages:
            if m["role"] == "user":
                lc.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                lc.append(AIMessage(content=m["content"]))
            else:
                lc.append(SystemMessage(content=m["content"]))
        for chunk in self._client.stream(lc):
            content = getattr(chunk, "content", "")
            if content:
                yield str(content)
