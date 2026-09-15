"""The Context Engine: assembles a budget-constrained context for the model.

This is requirement #1 of the job post. The engine decides *what goes into the
context window* — system prompt, retrieved knowledge, conversation history
(compressed), tool outputs — how big it is, and what gets trimmed when it
overflows. Callers only see a finalized :class:`Context` whose ``slots`` are
ready to render.
"""
from __future__ import annotations

import json
from typing import Optional

from .. import config
from ..schemas import Context, ContextSlot, HistoryTurn, RetrievedChunk
from .token_budget import TokenBudget, token_len


class ContextEngine:
    def __init__(
        self,
        budget: int,
        reranker: Optional[object] = None,
        summarizer: Optional[object] = None,
    ):
        self.budget = budget
        self.reranker = reranker
        self.summarizer = summarizer

    # -- helpers -----------------------------------------------------------------
    @staticmethod
    def _slot(kind: str, content: str, priority: int) -> ContextSlot:
        return ContextSlot(kind=kind, content=content, priority=priority, tokens=token_len(content))

    def _render_history(self, history: list[HistoryTurn]) -> str:
        lines = []
        for t in history:
            lines.append(f"用户：{t.user}")
            lines.append(f"助手：{t.assistant}")
        return "\n".join(lines)

    def _render_tool_results(self, tool_results: list[str]) -> str:
        if not tool_results:
            return ""
        return "\n".join(f"- {r}" for r in tool_results)

    # -- main ----------------------------------------------------------------------
    def build(
        self,
        *,
        user_input: str,
        retrieved: list[RetrievedChunk],
        history: list[HistoryTurn],
        system_prompt: str,
        tool_results: Optional[list[str]] = None,
        include_summary: bool = True,
    ) -> Context:
        tool_results = tool_results or []

        # 1) history -> (summary, recent) via sliding window + compression
        runner = _HistoryRunner(self.summarizer, max_keep=config.HISTORY_MAX_TURNS)
        summary_text, recent = runner.run(history)

        # 2) build slots (priority = importance when the budget trims)
        slots: list[ContextSlot] = [self._slot("system", system_prompt, priority=100)]

        if summary_text and include_summary:
            # 优先级 30：高于 history(25)、低于 tool(60)。
            # 理由：摘要是压缩过的，单位 token 的信息密度比未压缩的历史更高。
            slots.append(self._slot("summary", f"（对话摘要：{summary_text}）", priority=30))

        if tool_results:
            slots.append(self._slot("tool", "工具返回结果：\n" + self._render_tool_results(tool_results), priority=60))

        # retrieval: chunk per slot, priority from reranker
        if self.reranker is not None:
            retrieved = self.reranker.rerank(user_input, retrieved)
        for c in retrieved:
            body = c.text
            if c.source:
                body = f"[{c.source}] {body}"
            slots.append(self._slot("retrieval", body, priority=c.priority or 20))

        if recent:
            slots.append(self._slot("history", "对话历史：\n" + self._render_history(recent), priority=25))

        # 3) apply the token budget (trim lowest priority first)
        raw_ctx = Context(slots=slots, budget=self.budget)
        total = sum(s.tokens for s in slots)

        if total <= self.budget:
            raw_ctx.total_tokens = total
            raw_ctx.trimmed = 0
            return raw_ctx

        budget = TokenBudget(self.budget)
        slot_dicts = [{"kind": s.kind, "content": s.content, "priority": s.priority} for s in slots]
        # system slot 由 TokenBudget 按 kind 保护（永不裁，且保护所有 system 槽），
        # 所以数量兜底降到 1：min_keep=2 曾让「只剩 2 个 slot」时裁剪整体失效，
        # 预算被突破却静默不报（该事实现由 Context.over_budget 上报）。
        kept, trimmed_tokens = budget.allocate(slot_dicts, min_keep=1)

        kept_slots = [self._slot(d["kind"], d["content"], d["priority"]) for d in kept]

        return Context(
            slots=kept_slots,
            total_tokens=sum(s.tokens for s in kept_slots),
            budget=self.budget,
            trimmed=trimmed_tokens,
        )

    # -- rendering -------------------------------------------------------------------
    def render_messages(self, context: Context, user_input: str) -> list[dict]:
        """Turn the finalized context into model messages (system + turns + user)."""
        system_parts = []
        for s in context.slots:
            if s.kind == "system":
                system_parts.append(s.content)
            elif s.kind == "summary":
                system_parts.append(s.content)
            elif s.kind == "retrieval":
                system_parts.append(f"参考资料：{s.content}")
            elif s.kind == "history":
                system_parts.append(s.content)
            elif s.kind == "tool":
                system_parts.append(s.content)
        system_text = "\n".join(p for p in system_parts if p)
        return [{"role": "system", "content": system_text}, {"role": "user", "content": user_input}]

    def summarize_context(self, context: Context) -> str:
        """Pretty print the allocated context (used by the API / context panel)."""
        lines = [f"# Context (budget={self.budget}, trimmed={context.trimmed})"]
        for s in context.slots:
            preview = s.content if len(s.content) <= 80 else s.content[:77] + "..."
            lines.append(f"- [{s.kind:9s} prio={s.priority:3d} tok={s.tokens:4d}] {preview}")
        return "\n".join(lines)


class _HistoryRunner:
    """Small helper so the engine can be configured with a summarizer later."""

    def __init__(self, summarizer, max_keep: int = 8):
        self.summarizer = summarizer
        self.max_keep = max_keep

    def run(self, history: list[HistoryTurn]) -> tuple[str, list[HistoryTurn]]:
        if len(history) <= self.max_keep:
            return "", history
        old = history[: -self.max_keep]
        recent = history[-self.max_keep:]
        if self.summarizer is not None and hasattr(self.summarizer, "summarize_history"):
            summary = self.summarizer.summarize_history(old)
        else:
            last = old[-1]
            summary = f"早期对话共 {len(old)} 轮，最后提及：{last.user[:60]}"
        return summary, recent
