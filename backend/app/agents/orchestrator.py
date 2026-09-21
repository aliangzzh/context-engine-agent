"""Multi-agent orchestration (requirement #2).

This is a small, self-contained multi-agent *framework*: nodes (Router,
Retrieve, Tool, Writer) cooperate over a shared state machine, decorated with
lifecycle middleware hooks so an interviewer can see the design patterns behind
LangChain/LangGraph (nodes, conditional routing, tool calling, middleware).

Even though we implement it directly (so the demo runs offline with no heavy
deps), each concept maps one-to-one to LangGraph: ``add_node``, ``add_edge``,
conditional edges, ``StateGraph`` and ``checkpointer``. See ``docs/architecture.md``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

from ..context.engine import ContextEngine
from ..context.history import HistoryManager, HistoryTurn
from ..errors import AppError, ErrorCode
from ..models.base import ModelBackend
from ..retrieval.retriever import Retriever
from ..schemas import Context
from .router import route
from .tools import extract_args, get_tool, tool_descriptions
from .trace import Trace


# --- middleware -----------------------------------------------------------------
class Middleware:
    """Lifecycle hooks, mirroring LangChain ``before/after_model`` hooks."""

    def before_run(self, user_input: str) -> None:
        ...

    def after_run(self, result: "RunResult") -> None:
        ...

    def before_node(self, node: str, state: dict) -> None:
        ...

    def after_node(self, node: str, state: dict) -> None:
        ...


# --- result ----------------------------------------------------------------------
@dataclass
class RunResult:
    user_input: str
    answer: str
    context: Context
    trace: Trace
    retrieved: list
    tool_results: list[str]
    used_tools: list[str]
    messages: list[dict] = field(default_factory=list)
    session_id: str = "default"


# --- orchestrator ----------------------------------------------------------------
class AgentOrchestrator:
    _SYSTEM = (
        "你是一名专业的企业知识问答助手。请优先基于「参考资料」回答，"
        "如果参考资料为空则礼貌说明。若使用了工具，请结合工具返回结果作答。"
    )

    def __init__(
        self,
        retriever: Retriever,
        model: ModelBackend,
        history: HistoryManager,
        context_engine: ContextEngine,
        middleware: Optional[Middleware] = None,
    ):
        self.retriever = retriever
        self.model = model
        self.history = history
        self.engine = context_engine
        self.middleware = middleware or Middleware()

    def _route_steps(self, user_input: str) -> list[str]:
        kb_relevant = bool(self.retriever.search(user_input, k=1))
        return route(user_input, kb_relevant)

    def plan(self, user_input: str) -> list[dict]:
        """Show the router's plan (used by the API for the agent panel)."""
        steps = self._route_steps(user_input)
        return [
            {"name": s, "desc": self._describe_step(s)} for s in steps
        ] + [{"name": "writer", "desc": "汇总生成最终回答"}]

    @staticmethod
    def _describe_step(step: str) -> str:
        if step == "retrieve":
            return "检索 Agent：从知识库检索相关上下文"
        if step == "direct":
            return "直接进入写作 Agent"
        if step.startswith("tool:"):
            return f"工具 Agent：调用 {step.split(':')[1]}"
        return step

    @staticmethod
    def _missing_args_hint(name: str) -> str:
        """参数没抽出来时，给用户一句可执行的追问，而不是拿整句话去算。"""
        if name == "get_weather":
            return "没能从提问里识别出城市名，请补充城市（例如：北京今天天气怎么样）"
        if name == "calculator":
            return "没能识别出算式，请给出具体表达式（例如：计算 12*34+5）"
        return f"工具 {name} 缺少必要参数"

    def prepare(self, user_input: str, session_id: str = "default") -> RunResult:
        """Run the routing/retrieval/tool nodes and build the model messages."""
        self.middleware.before_run(user_input)
        trace = Trace()
        state: dict = {"user_input": user_input, "retrieved": [], "tool_results": []}

        steps = self._route_steps(user_input)
        trace.add("router", "router", "路由判定", {"plan": steps, "tools": tool_descriptions()})
        for step in steps:
            if step == "retrieve":
                self.middleware.before_node("retrieve", state)
                docs = self.retriever.search(user_input, k=None)
                state["retrieved"] = docs
                trace.add("retrieve", "retrieve", f"检索到 {len(docs)} 条知识", {"docs": [d.text[:80] for d in docs]})
                self.middleware.after_node("retrieve", state)
            elif step.startswith("tool:"):
                name = step.split(":", 1)[1]
                tool = get_tool(name)
                self.middleware.before_node("tool", state)
                if tool is None:
                    result = f"未知工具 {name}"
                    args: dict = {}
                else:
                    # function calling 的 arguments 那一步：从自然语言里抽参数
                    args = extract_args(name, user_input)
                    if tool.params and not args:
                        
                        result = self._missing_args_hint(name)
                    else:
                        result = tool.run(**args)
                state["tool_results"].append(f"{name} => {result}")
                trace.add("tool", "tool", f"调用工具 {name}",
                          {"args": args, "result": result[:120]})
                self.middleware.after_node("tool", state)
            elif step == "direct":
                trace.add("direct", "router", "无需检索/工具", {})

        # hand user request to the Context Engine for assembly
        history_turns = self.history.load()
        ctx = self.engine.build(
            user_input=user_input,
            retrieved=state["retrieved"],
            history=history_turns,
            system_prompt=self._SYSTEM,
            tool_results=state["tool_results"],
        )
        messages = self.engine.render_messages(ctx, user_input)

        res = RunResult(
            user_input=user_input,
            answer="",
            context=ctx,
            trace=trace,
            retrieved=state["retrieved"],
            tool_results=state["tool_results"],
            used_tools=[t for t in state["tool_results"]],
            messages=messages,
            session_id=session_id,
        )
        return res

    def generate(self, user_input: str, session_id: str = "default") -> RunResult:
        res = self.prepare(user_input, session_id)
        try:
            res.answer = self.model.generate(res.messages)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(ErrorCode.MODEL_ERROR, f"模型调用失败：{exc}")
        self.middleware.after_run(res)
        return res

    def stream_events(self, user_input: str, session_id: str = "default") -> Iterator[dict]:
        """Yield SSE-friendly events: agent steps, retrieved docs, tokens, done."""
        res = self.prepare(user_input, session_id)
        for step in res.trace.to_list():
            yield {"type": "agent", "data": step}
        yield {"type": "retrieved", "data": [d.model_dump() for d in res.retrieved]}

        answer_parts: list[str] = []
        try:
            for token in self.model.stream(res.messages):
                answer_parts.append(token)
                yield {"type": "token", "data": token}
        except AppError:
            raise
        except Exception as exc:
            raise AppError(ErrorCode.MODEL_ERROR, f"模型调用失败：{exc}")

        res.answer = "".join(answer_parts)
        self.middleware.after_run(res)

        # persist the new turn
        self.history.append(HistoryTurn(user=user_input, assistant=res.answer))
        yield {
            "type": "done",
            "data": {
                "answer": res.answer,
                "context": res.context.model_dump(),
                "trace": res.trace.to_list(),
                "used_tools": res.used_tools,
                "backend": self.model.name,
            },
        }
