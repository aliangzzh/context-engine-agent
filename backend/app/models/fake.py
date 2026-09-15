"""Deterministic offline model (used for tests and demos without an API key).

It does not use an LLM. It inspects the last user message and produces an
answer that demonstrates the full context-engine/agent wiring: it echoes the
retrieved context it was given so the frontend context panel visibly reflects
what was assembled.
"""
from __future__ import annotations

from typing import Iterable

from .base import ModelBackend


class FakeModel(ModelBackend):
    name = "fake"
    is_llm = False   # 没有真模型：能力相关的调用方必须走降级，而不是把话术当模型输出

    def _compose(self, question: str, refs: list[str], tool_results: list[str]) -> str:
        if tool_results:
            joined = "；".join(tool_results)
            return f"【离线演示】已调用工具并根据结果作答：{joined}（问题:{question}）"
        if not refs:
            return (
                f"【离线演示】针对「{question}」：当前为空检索（离线模式）。"
                "请配置 DASHSCOPE_API_KEY 或加载本地微调模型以获得真实回答。"
            )
        top = refs[0]
        return f"【离线演示】根据检索到的资料：{top}（问题：{question}）"

    def generate(self, messages: list[dict]) -> str:
        parts = []
        for m in messages:
            if m["role"] == "system":
                parts.append(m["content"])
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        refs = self._extract_refs(parts)
        tool_results = self._extract_tools(parts)
        return self._compose(last_user, refs, tool_results)

    def stream(self, messages: list[dict]) -> Iterable[str]:
        text = self.generate(messages)
        # stream by small chunks to mimic token streaming
        step = 6
        for i in range(0, len(text), step):
            yield text[i : i + step]

    @staticmethod
    def _extract_refs(parts: list[str]) -> list[str]:
        refs = []
        for p in parts:
            if "参考资料：" in p:
                body = p.split("参考资料：", 1)[1]
                refs.append(body[:70])
        return refs

    @staticmethod
    def _extract_tools(parts: list[str]) -> list[str]:
        results = []
        for p in parts:
            if "工具返回结果：" in p:
                body = p.split("工具返回结果：", 1)[1]
                for line in body.splitlines():
                    if line.strip().startswith("- "):
                        results.append(line.strip()[2:])
        return results
