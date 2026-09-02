"""FastAPI reference implementation (swap-in for server.py).

Requires ``pip install fastapi uvicorn``. Reuses the same framework-free
handlers from ``app/api.py`` so behaviour is identical to ``server.py``.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config
from . import api

app = FastAPI(title=config.APP_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    return {"name": config.APP_TITLE, "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    _, body = api.handle_health()
    return body


@app.post("/api/chat")
def chat(payload: dict):
    _, body = api.handle_chat(payload)
    return body


@app.post("/api/chat/plan")
def chat_plan(payload: dict):
    _, body = api.handle_chat_plan(payload)
    return body


@app.post("/api/chat/stream")
def chat_stream(payload: dict):
    _, events = api.handle_chat_stream(payload)

    async def gen():
        for evt in events:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/kb/ingest")
def ingest(payload: dict):
    _, body = api.handle_ingest(payload)
    return body
