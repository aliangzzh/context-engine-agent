"""Framework-free API handlers.

Keeps the business logic independent of the HTTP framework so the app can be
served either by:

* ``server.py``       - a zero-dependency stdlib HTTP server (runs now), or
* ``app/main.py``     - the FastAPI reference implementation (needs pip install)

约定（HTTP 协议 / JSON / 前后端分离 / 错误码）：

* 每个 handler 返回 ``(http_status, envelope)``；
* 成功：``{"code": 0, "msg": "ok", "data": ...}``
* 失败：``{"code": 40001, "msg": "...", "data": null, "detail": ...}``
* HTTP 状态码与业务 ``code`` 分离：状态码给网络层/网关看，code 给业务分支用。
"""
from __future__ import annotations

from typing import Any, Iterator

from .errors import AppError, ErrorCode, error_from_exception, fail, ok
from .logging_config import get_logger, log, set_request_id
from .multipart import parse_multipart
from .schemas import ChatRequest, ChatReply, FeedbackRequest, Health, IngestResult
from .services.chat_service import AppServices

logger = get_logger("app.api")

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
def handle_health() -> tuple[int, dict]:
    return 200, ok(services().health().model_dump())


def handle_chat(payload: dict) -> tuple[int, dict]:
    req = ChatRequest(**payload)
    return 200, ok(services().chat(req).model_dump())


def handle_chat_stream(payload: dict) -> tuple[int, Iterator[dict]]:
    req = ChatRequest(**payload)
    return 200, services().chat_stream(req)


def handle_chat_plan(payload: dict) -> tuple[int, dict]:
    req = ChatRequest(**payload)
    orch = services()._orchestrator(req.session_id)
    return 200, ok({"plan": orch.plan(req.message)})


def handle_ingest(payload: dict) -> tuple[int, dict]:
    """JSON 文本入库（老接口，保留兼容）。"""
    text = payload.get("text", "")
    filename = payload.get("filename", "upload")
    if not str(text).strip():
        raise AppError(ErrorCode.VALIDATION_ERROR, "text 不能为空")
    return 200, ok(services().ingest_text(text, filename).model_dump())


def handle_upload(content_type: str, body: bytes) -> tuple[int, dict]:
    """multipart 文件上传入库（前端「文件上传」走这里）。"""
    form = parse_multipart(content_type, body)
    file = form.first_file()
    if file is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "没有收到文件字段（form-data 里的 file）")
    result = services().ingest_upload(file.filename, file.data)
    log(logger, 20, "kb.upload", filename=file.filename, size=file.size, status=result.status)
    if result.status == "unsupported":
        # 类型不支持是客户端问题：415，但依然返回结构化结果方便前端提示
        return 415, fail(ErrorCode.UNSUPPORTED_MEDIA, f"不支持的文件类型：{result.filename}", result.model_dump())
    return 200, ok(result.model_dump())


def handle_kb_list(query: dict) -> tuple[int, dict]:
    """知识库文档列表（分页 + 搜索）。"""
    page = query.get("page", 1)
    size = query.get("size", 10)
    q = query.get("q", "")
    return 200, ok(services().kb_list(page=page, size=size, q=q))


def handle_kb_delete(source: str) -> tuple[int, dict]:
    if not source:
        raise AppError(ErrorCode.VALIDATION_ERROR, "source 不能为空")
    result = services().kb_delete(source)
    if result["deleted_chunks"] == 0 and result["deleted_rows"] == 0:
        raise AppError(ErrorCode.NOT_FOUND, f"知识库中没有来源：{source}")
    return 200, ok(result)


def handle_feedback(payload: dict) -> tuple[int, dict]:
    req = FeedbackRequest(**payload)
    row = services().add_feedback(req.session_id, req.message, req.answer, req.reason, req.note)
    return 200, ok(row)


def handle_feedback_list(query: dict) -> tuple[int, dict]:
    return 200, ok(services().list_feedback(page=query.get("page", 1), size=query.get("size", 10)))


def handle_stats() -> tuple[int, dict]:
    return 200, ok(services().stats())


def handle_context(session_id: str) -> tuple[int, dict]:
    svc = services()
    turns = svc._history(session_id).load()
    return 200, ok({"session_id": session_id, "turns": len(turns),
                    "history": [t.__dict__ for t in turns]})


# --- 统一异常包装 ---------------------------------------------------------------------
def safe_call(fn, *args, **kwargs) -> tuple[int, dict]:
    """把 handler 的异常统一转成 ``(status, envelope)``，并写日志。

    不给任何未预期异常泄露堆栈，但日志里保留 —— 这正是
    "异常处理与日志记录"。
    """
    try:
        return fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 - 这里就是统一兜底的地方
        status, body = error_from_exception(exc)
        if status >= 500:
            log(logger, 40, "api.error", path=getattr(fn, "__name__", "?"),
                code=body.get("code"), error=exc.__class__.__name__, msg=str(exc)[:200])
        else:
            log(logger, 30, "api.rejected", path=getattr(fn, "__name__", "?"),
                code=body.get("code"), msg=body.get("msg"))
        return status, body


def begin_request(rid: str | None = None) -> str:
    """给每个进入的请求分配 request_id（日志里全程可见）。"""
    return set_request_id(rid)


__all__ = [
    "Any", "AppError", "ChatReply", "Health", "IngestResult",
    "begin_request", "handle_chat", "handle_chat_plan", "handle_chat_stream",
    "handle_context", "handle_feedback", "handle_feedback_list", "handle_health",
    "handle_ingest", "handle_kb_delete", "handle_kb_list", "handle_stats",
    "handle_upload", "reset_services", "safe_call", "services",
]
