"""Framework-free API handlers.

Keeps the business logic independent of the HTTP framework so the app can be
served either by:

* ``server.py``       - a zero-dependency stdlib HTTP server (runs now), or
* ``app/main.py``     - the FastAPI reference implementation (needs pip install)

Each handler is a plain function returning ``(status_code, body)`` where
``body`` is either a JSON-serialisable object or a generator of SSE events.
"""
from __future__ import annotations

from typing import Any, Iterator

from .schemas import ChatRequest, ChatReply, Health, IngestResult
from .services.chat_service import AppServices

_services: AppServices | None = None


def services() -> AppServices:
    global _services
    if _services is None:
        _services = AppServices(seed_kb=True)
    return _services


def reset_services() -> None:
    """Used by tests to rebuild with a fresh KB."""
    global _services
    _services = None


# --- handlers ---------------------------------------------------------------------
def handle_health() -> tuple[int, Health | dict]:
    return 200, services().health()


def handle_chat(payload: dict) -> tuple[int, ChatReply | dict]:
    req = ChatRequest(**payload)
    return 200, services().chat(req)


def handle_chat_stream(payload: dict) -> tuple[int, Iterator[dict]]:
    req = ChatRequest(**payload)
    return 200, services().chat_stream(req)


def handle_chat_plan(payload: dict) -> tuple[int, dict]:
    req = ChatRequest(**payload)
    orch = services()._orchestrator(req.session_id)
    return 200, {"plan": orch.plan(req.message)}


def handle_ingest(payload: dict) -> tuple[int, IngestResult | dict]:
    text = payload.get("text", "")
    filename = payload.get("filename", "upload")
    return 200, services().ingest_text(text, filename)


def handle_context(session_id: str) -> tuple[int, dict]:
    svc = services()
    history = svc._history(session_id)
    turns = history.load()
    return 200, {"session_id": session_id, "turns": len(turns), "history": [t.__dict__ for t in turns]}
