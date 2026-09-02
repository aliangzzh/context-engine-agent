"""Multi-agent orchestration package (requirement #2)."""
from .orchestrator import AgentOrchestrator, Middleware, RunResult
from .tools import TOOLS, get_tool, tool_descriptions
from .trace import Trace, TraceStep

__all__ = [
    "AgentOrchestrator", "Middleware", "RunResult",
    "TOOLS", "get_tool", "tool_descriptions", "Trace", "TraceStep",
]
