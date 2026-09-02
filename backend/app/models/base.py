"""Model backend abstraction.

Three implementations, selected by config:

* ``FakeModel``   - deterministic, offline (default when no key/adapter).
* ``QwenApiModel``- Alibaba Tongyi (DashScope) chat model.
* ``LocalFTModel``- a locally LoRA-fine-tuned Qwen2.5 via transformers + peft.

All share ``generate``/``stream`` so the agent orchestrator and the HTTP layer
are independent of which one is running.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable


class ModelBackend(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, messages: list[dict]) -> str:
        ...

    @abstractmethod
    def stream(self, messages: list[dict]) -> Iterable[str]:
        ...

    @property
    def label(self) -> str:
        return self.name
