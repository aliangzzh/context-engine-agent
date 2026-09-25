"""Pydantic schemas shared across the API, context engine and agent layer.

These are deliberately plain data containers so that the Context Engine and the
agent orchestrator can be unit-tested without spinning up the HTTP server.
"""
from __future__ import annotations

from typing import Any, Literal

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
    #: 运行时**实际生效**的检索后端。索引不可用/与语料不一致时会降级成 bm25。
    #: 只看 retrieval_backend（配置层意愿）会被误导——排查请以本字段为准。
    retrieval_effective: str = ""
    #: 向量索引状态摘要：status / chunk_count / built_at / last_degrade
    vector_index: dict = Field(default_factory=dict)


class IngestResult(BaseModel):
    status: str
    chunks: int = 0
    filename: str = ""
    reason: str = Field(default="", description="skipped/unsupported 时的原因")


class FeedbackRequest(BaseModel):
    """badcase 反馈。"""

    session_id: str = Field(default="default", description="会话 id")
    message: str = Field(..., min_length=1, description="用户当时的问题")
    answer: str = Field(default="", description="模型当时的回答")
    reason: str = Field(..., description="answer_wrong | hallucination | missing_kb | too_slow | other")
    note: str = Field(default="", max_length=500, description="补充说明")
