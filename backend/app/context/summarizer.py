"""对话摘要器：把被滑窗挤出去的旧轮次压成一段要点。"""
from __future__ import annotations

from .history import HistoryTurn


class HistorySummarizer:
    """拿着一个模型，把旧轮次压成要点。

    只有真正调用 LLM 的后端（``is_llm is True``）才走模型；离线 ``FakeModel``
    不认摘要提示词，会把整段旧对话原样吐回来（实测 87 tokens 原文 -> 146 tokens
    摘要 slot），等于把"压缩"做成"重复注入"。所以这里对非 LLM 后端直接降级为规则
    模板：宁可摘要不聪明，也不能让它比原文更长。
    """

    _SYSTEM = (
        "你是对话摘要助手。请把给出的多轮对话压缩成 3 句以内的要点，"
        "保留关键事实、数字与结论，不要编造。"
    )

    def __init__(self, model):          # ← 新加：从外面"请"一个模型进来
        self.model = model

    @staticmethod
    def _fallback(turns: list[HistoryTurn]) -> str:
        """规则模板降级：是"降级"，不是"变成空"。"""
        last = turns[-1]
        return f"早期对话共 {len(turns)} 轮，最后提及：{last.user[:60]}"

    def summarize_history(self, turns: list[HistoryTurn]) -> str:
        if not turns:
            return ""
        # 离线假模型没有摘要能力，调用它只会把旧对话原样放大回来。
        if not getattr(self.model, "is_llm", True):
            return self._fallback(turns)
        text = "\n".join(f"用户：{t.user}\n助手：{t.assistant}" for t in turns)
        try:
            summary = self.model.generate([          # ← 调模型（项目里现成的方法）
                {"role": "system", "content": self._SYSTEM},
                {"role": "user", "content": text},
            ])
        except Exception:
            return self._fallback(turns)
        return (summary or "").strip()
