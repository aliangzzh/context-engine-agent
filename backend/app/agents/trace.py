"""Agent trace recording so the frontend can render the collaborating chain."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TraceStep:
    node: str
    kind: str                     # router | retrieve | tool | writer | model
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node": self.node,
            "kind": self.kind,
            "summary": self.summary,
            "detail": self.detail,
            "ts": datetime.now().strftime("%H:%M:%S"),
        }


class Trace:
    def __init__(self):
        self.steps: list[TraceStep] = []

    def add(self, node: str, kind: str, summary: str, detail: dict | None = None) -> None:
        self.steps.append(TraceStep(node=node, kind=kind, summary=summary, detail=detail or {}))

    def to_list(self) -> list[dict]:
        return [s.to_dict() for s in self.steps]
