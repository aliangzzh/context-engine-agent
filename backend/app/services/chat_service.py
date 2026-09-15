"""Application service facade that wires the whole stack together.

Owns the singletons (retriever, model, context engine, SQL repositories) and
exposes the high-level operations the HTTP layer calls. The orchestrator is built
per request so that each session gets its own history handle.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

from .. import config
from ..agents.orchestrator import AgentOrchestrator
from ..context.engine import ContextEngine
from ..context.history import ChatStore, HistoryManager, HistoryTurn
from ..context.rerank import Reranker
from ..context.summarizer import HistorySummarizer
from ..logging_config import get_logger, log
from ..metrics import get_metrics
from ..models import get_model_backend
from ..retrieval.knowledge import KnowledgeBase
from ..retrieval.retriever import get_retriever
from ..schemas import ChatReply, ChatRequest, Health, IngestResult
from ..storage.repo import FeedbackRepository, KbRepository

logger = get_logger("app.services")


class AppServices:
    def __init__(self, seed_kb: bool = True):
        self.retriever = get_retriever()
        self.model = get_model_backend()
        self.store = ChatStore(config.DATA_DIR / "chat_history")
        self.kb_repo = KbRepository()
        self.feedback_repo = FeedbackRepository()
        self.metrics = get_metrics()
        self.engine = ContextEngine(
            config.CONTEXT_TOKEN_BUDGET,
            reranker=Reranker(),
            summarizer=HistorySummarizer(self.model),  # ← 模型摘要（失败降级规则模板）
        )
        if seed_kb and not self.retriever.texts and self.kb_repo.stats()["chunks"] == 0:
            self._seed_demo_kb()

    def _history(self, session_id: str) -> HistoryManager:
        return HistoryManager(
            self.store, session_id,
            max_turns=config.HISTORY_MAX_TURNS,
            summary_tokens=config.HISTORY_SUMMARY_TOKENS,
        )

    def _orchestrator(self, session_id: str) -> AgentOrchestrator:
        return AgentOrchestrator(self.retriever, self.model, self._history(session_id), self.engine)

    def kb(self) -> KnowledgeBase:
        return KnowledgeBase(self.retriever, self.kb_repo)

    # -- health ---------------------------------------------------------------------
    def health(self) -> Health:
        return Health(
            status="ok",
            chat_backend=config.effective_chat_backend(),
            retrieval_backend=config.effective_retrieval_backend(),
            model=self.model.name,
            db_backend=config.effective_db_backend(),
            cache_backend=config.effective_cache_backend(),
        )

    # -- chat ------------------------------------------------------------------------
    def chat(self, req: ChatRequest) -> ChatReply:
        start = time.perf_counter()
        history = self._history(req.session_id)
        orch = AgentOrchestrator(self.retriever, self.model, history, self.engine)
        res = orch.generate(req.message, req.session_id)
        history.store.save(req.session_id, history.load() + [HistoryTurn(user=req.message, assistant=res.answer)])
        elapsed = int((time.perf_counter() - start) * 1000)
        self.metrics.record({
            "session_id": req.session_id,
            "tokens": res.context.total_tokens,
            "budget": res.context.budget,
            "over_budget": res.context.over_budget,
            "elapsed_ms": elapsed,
            "tools": res.used_tools,
            "nodes": len(res.trace.to_list()),
        })
        return ChatReply(
            answer=res.answer,
            session_id=req.session_id,
            context=res.context,
            agent_trace=res.trace.to_list(),
            used_tools=res.used_tools,
            backend=self.model.name,
            tokens_requested=res.context.total_tokens,
            tokens_generated=len(res.answer),
            elapsed_ms=elapsed,
        )

    def chat_stream(self, req: ChatRequest) -> Iterator[dict]:
        """SSE 事件流（生成器）。在 done 事件处补一次指标采集。"""
        started = time.perf_counter()
        orch = self._orchestrator(req.session_id)
        for evt in orch.stream_events(req.message, req.session_id):
            if evt.get("type") == "done":
                ctx = evt.get("data", {}).get("context", {}) or {}
                self.metrics.record({
                    "session_id": req.session_id,
                    "tokens": ctx.get("total_tokens", 0),
                    "budget": ctx.get("budget", 0),
                    "over_budget": bool(ctx.get("total_tokens", 0) > ctx.get("budget", 0)),
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "tools": evt.get("data", {}).get("used_tools", []),
                    "nodes": len(evt.get("data", {}).get("trace", [])),
                })
            yield evt

    # -- ingestion / 知识库管理 ---------------------------------------------------------
    def ingest_text(self, text: str, filename: str = "upload") -> IngestResult:
        r = self.kb().ingest_text(text, filename)
        return IngestResult(status=r["status"], chunks=r["chunks"], filename=r["filename"],
                            reason=r.get("reason", ""))

    def ingest_upload(self, filename: str, data: bytes) -> IngestResult:
        r = self.kb().ingest_upload(filename, data)
        return IngestResult(status=r["status"], chunks=r["chunks"], filename=r["filename"],
                            reason=r.get("reason", ""))

    def ingest_kb_dir(self, directory: Path) -> list[dict]:
        kb = self.kb()
        return [kb.ingest_file(f) for f in Path(directory).glob("*.txt")]

    def kb_list(self, page: int = 1, size: int = 10, q: str = "") -> dict:
        return self.kb().list_sources(page=page, size=size, q=q)

    def kb_delete(self, source: str) -> dict:
        return self.kb().delete_source(source)

    # -- badcase 反馈 ------------------------------------------------------------------
    def add_feedback(self, session_id: str, message: str, answer: str, reason: str, note: str = "") -> dict:
        row = self.feedback_repo.add(session_id, message, answer, reason, note)
        self.metrics.incr("feedback", 1)
        log(logger, 20, "feedback.added", reason=reason, session_id=session_id)
        return row

    def list_feedback(self, page: int = 1, size: int = 10) -> dict:
        return self.feedback_repo.list(page=page, size=size)

    # -- 看板 -------------------------------------------------------------------------
    def stats(self) -> dict:
        """看板数据：知识库规模 + badcase 分布 + 最近请求的 token/耗时序列。"""
        return {
            "kb": dict(self.kb_repo.stats(), chunk_lengths=self.kb_repo.chunk_length_histogram()),
            "feedback": {
                "total": self.feedback_repo.list(page=1, size=1)["total"],
                "distribution": self.feedback_repo.distribution(),
            },
            "requests": self.metrics.summary(),
            "runtime": {
                "chat_backend": config.effective_chat_backend(),
                "retrieval_backend": config.effective_retrieval_backend(),
                "db_backend": config.effective_db_backend(),
                "cache_backend": config.effective_cache_backend(),
                "context_budget": config.CONTEXT_TOKEN_BUDGET,
                "history_max_turns": config.HISTORY_MAX_TURNS,
                "top_k": config.TOP_K,
                "chunk_size": config.CHUNK_SIZE,
                "chunk_strategy": config.CHUNK_STRATEGY,
            },
        }

    # -- demo seed ---------------------------------------------------------------------
    def _seed_demo_kb(self) -> None:
        samples = [
            ("尺码推荐.txt", "尺码推荐：身高170厘米，体重90–115斤建议M码；体重115–135斤建议L码。牛仔裤尺码按腰围选，宽松款可大一号。"),
            ("洗涤养护.txt", "加绒牛仔：水温≤30℃，中性洗涤剂，翻面清洗，机洗选轻柔模式，避免长时间浸泡。收纳时折叠平放，避免重压破坏绒层。纯棉保暖内衣：可机洗或手洗，水温≤30℃，禁止使用漂白剂。德绒材质避免高温熨烫。"),
            ("颜色选择.txt", "春季适合清新柔和的颜色：樱花粉、薄荷绿、浅蓝色。服装搭配遵循三色原则，全身颜色不超过三种，同色系相近色更容易显高级。"),
        ]
        for name, text in samples:
            try:
                self.ingest_text(text, name)
            except Exception:
                log(logger, 30, "kb.seed_failed", source=name)


def build_services() -> AppServices:
    return AppServices()
