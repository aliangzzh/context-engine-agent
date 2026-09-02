"""Model backend factory (requirement #3 inference wiring)."""
from __future__ import annotations

from .. import config
from .base import ModelBackend


def get_model_backend(backend: str | None = None) -> ModelBackend:
    backend = backend or config.effective_chat_backend()
    if backend == "qwen_api":
        return _safe(lambda: __import__("app.models.qwen_api", fromlist=["QwenApiModel"]).QwenApiModel())
    if backend == "local_ft":
        return _safe(lambda: __import__("app.models.local_ft", fromlist=["LocalFTModel"]).LocalFTModel())
    # fallback
    from .fake import FakeModel
    return FakeModel()


def _safe(ctor):
    """If the real backend cannot be constructed (missing key/deps) fall back."""
    try:
        return ctor()
    except Exception:
        from .fake import FakeModel
        return FakeModel()
