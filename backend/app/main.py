"""FastAPI reference implementation (swap-in for server.py).

Requires ``pip install fastapi uvicorn``. Reuses the same framework-free
handlers from ``app/api.py`` so behaviour is identical to ``server.py``.

Python/FastAPI 接口开发，以及 API 接口设计讨论与
OpenAPI/Swagger 文档维护」：

* 请求体用 pydantic 模型声明（Swagger 里能直接看到字段与校验规则）；
* 每个接口有 tag / summary / 错误响应说明，``/docs`` 可直接当接口文档给前端；
* 路由声明为 ``async def``，阻塞型业务（检索、SQL、模型调用）丢到线程池，
  避免卡住事件循环 —— 这正是"异步与 GIL"该怎么讲的地方：
  IO 等待期间让出事件循环，CPU 密集的活仍受 GIL 限制，所以用线程池而不是硬扛。
"""
from __future__ import annotations

import json
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from . import api, config
from .errors import AppError, ErrorCode, error_from_exception, fail
from .logging_config import get_logger, log, set_request_id, setup_logging
from .schemas import ChatRequest, FeedbackRequest

setup_logging()
logger = get_logger("app.http")

app = FastAPI(
    title=config.APP_TITLE,
    version="1.1.0",
    description=(
        "上下文引擎 + 多 Agent 协作 + RAG 问答的接口文档。\n\n"
        "**统一响应结构**：`{code, msg, data}`；`code=0` 表示业务成功，"
        "非 0 见 `app/errors.py` 的错误码表（40xxx 调用方 / 50xxx 服务端 / 502xx 上游）。"
    ),
    openapi_tags=[
        {"name": "ops", "description": "健康检查与看板统计"},
        {"name": "chat", "description": "对话（含 SSE 流式）与 Agent 规划"},
        {"name": "kb", "description": "知识库：文本入库、文件上传、列表分页、删除"},
        {"name": "feedback", "description": "badcase 反馈的收集与查询"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# --- 横切关注点：request_id + 访问日志 + 耗时 -------------------------------------------
@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = set_request_id(request.headers.get("X-Request-ID"))
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - 兜底成统一响应
        status, body = error_from_exception(exc)
        log(logger, 40, "http.unhandled", path=request.url.path, error=exc.__class__.__name__)
        response = JSONResponse(status_code=status, content=body)
    response.headers["X-Request-ID"] = rid
    log(
        logger,
        20,
        "http",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return response


# --- 统一异常处理 ------------------------------------------------------------------
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.http_status, content=fail(exc.code, exc.msg, exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    detail = [{"field": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
              for e in exc.errors()]
    return JSONResponse(
        status_code=400,
        content=fail(ErrorCode.VALIDATION_ERROR, "参数校验失败", detail),
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log(logger, 40, "http.error", path=request.url.path, error=exc.__class__.__name__)
    return JSONResponse(status_code=500, content=fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误"))


# --- ops --------------------------------------------------------------------------
@app.get("/", tags=["ops"], summary="服务信息")
async def root() -> dict:
    return api.ok({"name": config.APP_TITLE, "docs": "/docs", "health": "/health"})


@app.get("/health", tags=["ops"], summary="健康检查（含实际生效的后端）")
async def health() -> dict:
    status, body = api.handle_health()
    return body


@app.get("/api/stats", tags=["ops"], summary="看板统计：知识库规模 / badcase 分布 / 最近请求指标")
async def stats() -> dict:
    status, body = api.handle_stats()
    return body


# --- chat -------------------------------------------------------------------------
@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答",
          responses={400: {"description": "参数校验失败(40001)"}})
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return body


@app.post("/api/chat/plan", tags=["chat"], summary="只看路由/工具计划（不调用模型）")
async def chat_plan(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat_plan, payload.model_dump())
    return body


@app.post("/api/chat/stream", tags=["chat"], summary="SSE 流式回答（agent/token/retrieved/done）")
async def chat_stream(payload: ChatRequest):
    status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())

    async def gen():
        for evt in events:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- kb ---------------------------------------------------------------------------
@app.post("/api/kb/ingest", tags=["kb"], summary="文本入库（JSON）")
async def ingest(payload: dict) -> dict:
    status, body = await run_in_threadpool(api.handle_ingest, payload)
    return JSONResponse(status_code=status, content=body)


@app.post("/api/kb/upload", tags=["kb"], summary="文件上传入库（multipart/form-data）",
          responses={415: {"description": "不支持的文件类型(41500)"},
                     413: {"description": "文件过大(41300)"}})
async def upload(request: Request):
    body_bytes = await request.body()
    status, envelope = await run_in_threadpool(
        api.handle_upload, request.headers.get("content-type", ""), body_bytes
    )
    return JSONResponse(status_code=status, content=envelope)


@app.get("/api/kb/list", tags=["kb"], summary="知识库文档列表（分页 + 搜索）")
async def kb_list(page: int = 1, size: int = 10, q: str = "") -> dict:
    status, body = await run_in_threadpool(api.handle_kb_list, {"page": page, "size": size, "q": q})
    return JSONResponse(status_code=status, content=body)


@app.delete("/api/kb/{source}", tags=["kb"], summary="按来源删除文档（同时清理检索索引）",
            responses={404: {"description": "来源不存在(40400)"}})
async def kb_delete(source: str) -> dict:
    status, body = await run_in_threadpool(api.handle_kb_delete, source)
    return JSONResponse(status_code=status, content=body)


# --- feedback ---------------------------------------------------------------------
@app.post("/api/feedback", tags=["feedback"], summary="提交 badcase 反馈")
async def feedback(payload: FeedbackRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_feedback, payload.model_dump())
    return JSONResponse(status_code=status, content=body)


@app.get("/api/feedback", tags=["feedback"], summary="badcase 列表（分页）")
async def feedback_list(page: int = 1, size: int = 10) -> dict:
    status, body = await run_in_threadpool(api.handle_feedback_list, {"page": page, "size": size})
    return JSONResponse(status_code=status, content=body)


@app.get("/api/context/{session_id}", tags=["chat"], summary="会话历史（上下文面板用）")
async def context(session_id: str) -> dict:
    status, body = await run_in_threadpool(api.handle_context, session_id)
    return body
