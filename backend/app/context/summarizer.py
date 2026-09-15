"""对话摘要器：把被滑窗挤出去的旧轮次压成一段要点。"""
from __future__ import annotations

from .history import HistoryTurn


class HistorySummarizer:
    """拿着一个模型，把旧轮次压成要点。"""

    _SYSTEM = (
        "你是对话摘要助手。请把给出的多轮对话压缩成 3 句以内的要点，"
        "保留关键事实、数字与结论，不要编造。"
    )

    def __init__(self, model):          # ← 新加：从外面"请"一个模型进来
        self.model = model

    def summarize_history(self, turns: list[HistoryTurn]) -> str:
        if not turns:
            return ""
        text = "\n".join(f"用户：{t.user}\n助手：{t.assistant}" for t in turns)
        try:
            summary = self.model.generate([          # ← 调模型（项目里现成的方法）
                {"role": "system", "content": self._SYSTEM},
                {"role": "user", "content": text},
            ])
        except Exception:
            # 兜底：退回规则模板（是"降级"，不是"变成空"）
            last = turns[-1]
            return f"早期对话共 {len(turns)} 轮，最后提及：{last.user[:60]}"
        return (summary or "").strip()