"""Pydantic schemas shared across the API, context engine and agent layer.

These are deliberately plain data containers so that the Context Engine and the
agent orchestrator can be unit-tested without spinning up the HTTP server.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from pydantic import BaseModel, Field, computed_field


# --- Chat request / response ----------------------------------------------------
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's question")
    session_id: str = Field(default="default", description="Conversation id")
    stream: bool = Field(default=True, description="Stream tokens when True")


# --- Context Engine -------------------------------------------------------------
class RetrievedChunk(BaseModel):
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    source: str = ""


class HistoryTurn(BaseModel):
    user: str
    assistant: str


class ContextSlot(BaseModel):
    """One allocated slice of the context window with its priority."""

    kind: Literal["system", "summary", "retrieval", "history", "tool"]
    content: str
    priority: int = Field(default=0, description="Higher wins when trimming")
    tokens: int = 0


class Context(BaseModel):
    """The final, budget-constrained context handed to the model."""

    slots: list[ContextSlot] = Field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    trimmed: int = Field(default=0, description="Tokens removed to fit budget")

    @computed_field
    @property
    def over_budget(self) -> bool:
        """单一口径的「是否超预算」——由后端算，前端不再自己判断。"""
        return self.total_tokens > self.budget


class ChatReply(BaseModel):
    """Structured reply returned to the frontend for the context panel."""

    answer: str
    session_id: str
    context: Context
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)
    backend: str = "fake"
    tokens_requested: int = 0
    tokens_generated: int = 0
    elapsed_ms: int = 0


class Health(BaseModel):
    status: Literal["ok"]
    chat_backend: str
    retrieval_backend: str
    model: str = ""
    db_backend: str = ""      # sqlite | mysql
    cache_backend: str = ""   # lru | redis


class IngestResult(BaseModel):
    status: str
    chunks: int = 0
    filename: str = ""
