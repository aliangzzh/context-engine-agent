"""Application service facade that wires the whole stack together.

Owns the singletons (retriever, model, context engine) and exposes the
high-level operations the HTTP layer calls. The orchestrator is built per
request so that each session gets its own history handle.
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
from ..models import get_model_backend
from ..retrieval.knowledge import KnowledgeBase
from ..retrieval.retriever import get_retriever
from ..schemas import ChatReply, ChatRequest, Health, IngestResult


class AppServices:
    def __init__(self, seed_kb: bool = True):
        self.retriever = get_retriever()
        self.model = get_model_backend()
        self.store = ChatStore(config.DATA_DIR / "chat_history")
        self.engine = ContextEngine(
            config.CONTEXT_TOKEN_BUDGET,
            reranker=Reranker(),
            summarizer=HistorySummarizer(self.model),  # ← 新增
        )
        if seed_kb and not self.retriever.texts:
            self._seed_demo_kb()

    def _history(self, session_id: str) -> HistoryManager:
        return HistoryManager(
            self.store, session_id,
            max_turns=config.HISTORY_MAX_TURNS,
            summary_tokens=config.HISTORY_SUMMARY_TOKENS,
        )

    def _orchestrator(self, session_id: str) -> AgentOrchestrator:
        return AgentOrchestrator(self.retriever, self.model, self._history(session_id), self.engine)

    # -- health ---------------------------------------------------------------------
    def health(self) -> Health:
        return Health(
            status="ok",
            chat_backend=config.effective_chat_backend(),
            retrieval_backend=config.effective_retrieval_backend(),
            model=self.model.name,
        )

    # -- chat ------------------------------------------------------------------------
    def chat(self, req: ChatRequest) -> ChatReply:
        start = time.perf_counter()
        history = self._history(req.session_id)
        orch = AgentOrchestrator(self.retriever, self.model, history, self.engine)
        res = orch.generate(req.message, req.session_id)
        history.store.save(req.session_id, history.load() + [HistoryTurn(user=req.message, assistant=res.answer)])
        elapsed = int((time.perf_counter() - start) * 1000)
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
        orch = self._orchestrator(req.session_id)
        yield from orch.stream_events(req.message, req.session_id)

    # -- ingestion ---------------------------------------------------------------------
    def ingest_text(self, text: str, filename: str = "upload") -> IngestResult:
        kb = KnowledgeBase(self.retriever)
        r = kb.ingest_text(text, filename)
        return IngestResult(status=r["status"], chunks=r["chunks"], filename=r["filename"])

    def ingest_kb_dir(self, directory: Path) -> list[dict]:
        kb = KnowledgeBase(self.retriever)
        out = []
        for f in Path(directory).glob("*.txt"):
            out.append(kb.ingest_file(f))
        return out

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
                pass


def build_services() -> AppServices:
    return AppServices()
