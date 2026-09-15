"""Zero-dependency HTTP server (stdlib only) that runs the demo right now.

Serves the static single-file UI at ``/`` and the JSON / SSE API under ``/api``.
No pip install required (uses the stdlib ``http.server``; the app logic needs
only pydantic / python-dotenv / requests, all present on the base interpreter).

Optional upgrade path: ``pip install fastapi uvicorn`` and run ``app/main.py``
(the FastAPI reference implementation) against the same ``app/api.py`` handlers.

这里同时承担"日志与异常"的职责：
* 每个请求分配 ``request_id``，日志行与响应头都能看到；
* 所有 handler 走 ``safe_call``，异常统一变成 ``{code,msg,data}``；
* 访问日志记录 方法/路径/状态码/耗时。
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from app import config
from app.api import (
    begin_request, handle_chat, handle_chat_plan, handle_chat_stream,
    handle_context, handle_feedback, handle_feedback_list, handle_health,
    handle_ingest, handle_kb_delete, handle_kb_list, handle_stats, handle_upload,
    safe_call,
)
from app.errors import ErrorCode, error_from_exception, fail
from app.logging_config import get_logger, setup_logging
from app.multipart import MAX_UPLOAD_BYTES

logger = get_logger("app.server")

STATIC_DIR = config.PROJECT_DIR / "frontend" / "static"


def _jsonable(value):
    """Recursively coerce Pydantic models / dataclasses / dates to JSON-safe types."""
    from dataclasses import asdict, is_dataclass
    from datetime import datetime
    try:
        from pydantic import BaseModel
        if isinstance(value, BaseModel):
            return value.model_dump()
    except Exception:
        pass
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "ContextEngine/1.0"

    # --- helpers -----------------------------------------------------------------
    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed = config.ALLOW_ORIGINS + ["http://localhost:5173"]
        if origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Request-ID")

    def _send_json(self, code: int, body) -> None:
        data = json.dumps(_jsonable(body), ensure_ascii=False).encode("utf-8")
        self._status = code
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Request-ID", getattr(self, "rid", "-"))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_UPLOAD_BYTES:
            raise ValueError(f"请求体超过上限 {MAX_UPLOAD_BYTES // 1024} KB")
        return self.rfile.read(length) if length else b""

    def _read_json(self) -> dict:
        raw = self._read_body()
        if not raw.strip():
            return {}
        try:
            # utf-8-sig: 容忍 Windows 工具写入的 UTF-8 BOM
            return json.loads(raw.decode("utf-8-sig"))
        except Exception:
            # 让调用方回 400，而不是抛到 socketserver 里把连接直接掐断。
            raise ValueError("invalid JSON body")

    def _query(self) -> dict:
        qs = parse_qs(urlparse(self.path).query)
        return {k: v[0] for k, v in qs.items() if v}

    def _send_file(self, path: Path) -> None:
        data = path.read_bytes()
        self._status = 200
        self.send_response(200)
        self._cors()
        ct = "text/html; charset=utf-8" if path.suffix == ".html" else "application/octet-stream"
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, events) -> None:
        self._status = 200
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for evt in events:
                chunk = f"data: {json.dumps(_jsonable(evt), ensure_ascii=False)}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return  # 客户端断开（前端点停止 / 关页面），正常现象
        except Exception as exc:  # 流已经开了，只能把错误当成一个事件发出去
            _, body = error_from_exception(exc)
            payload = {"type": "error",
                       "data": {"code": body.get("code", int(ErrorCode.INTERNAL_ERROR)),
                                "msg": body.get("msg", "服务器内部错误")}}
            try:
                self.wfile.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

    def _send_error(self, exc: BaseException) -> None:
        """把未捕获异常转成 JSON 错误响应（原本会直接断开连接）。"""
        status, body = error_from_exception(exc)
        try:
            self._send_json(status, body)
        except Exception:
            pass  # SSE 等已经开始写响应体的场景，只能放弃本次响应

    def log_message(self, fmt, *args):  # 访问日志统一交给 logging
        return

    def _access_log(self, started: float) -> None:
        logger.info(
            "http",
            extra={"extra_fields": {
                "method": self.command,
                "path": urlparse(self.path).path,
                "status": getattr(self, "_status", 0),
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }},
        )

    # --- HTTP methods -------------------------------------------------------------
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        started = time.perf_counter()
        self.rid = begin_request(self.headers.get("X-Request-ID"))
        self._status = 0
        path = urlparse(self.path).path
        try:
            if path == "/health":
                status, body = safe_call(handle_health)
                return self._send_json(status, body)
            if path == "/api/stats":
                status, body = safe_call(handle_stats)
                return self._send_json(status, body)
            if path == "/api/kb/list":
                status, body = safe_call(handle_kb_list, self._query())
                return self._send_json(status, body)
            if path == "/api/feedback":
                status, body = safe_call(handle_feedback_list, self._query())
                return self._send_json(status, body)
            if path.startswith("/api/context/"):
                sid = unquote(path.rsplit("/", 1)[1])
                status, body = safe_call(handle_context, sid)
                return self._send_json(status, body)
            if path in ("/", "/index.html"):
                index = STATIC_DIR / "index.html"
                if index.exists():
                    return self._send_file(index)
                return self._send_json(200, {"code": 0, "msg": "static UI not found",
                                             "data": {"static_dir": str(STATIC_DIR)}})
            return self._send_json(404, fail(ErrorCode.NOT_FOUND, f"未知路径：{path}"))
        except Exception as exc:  # noqa: BLE001
            return self._send_error(exc)
        finally:
            self._access_log(started)

    def do_DELETE(self) -> None:
        started = time.perf_counter()
        self.rid = begin_request(self.headers.get("X-Request-ID"))
        self._status = 0
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/kb/"):
                source = unquote(path[len("/api/kb/"):])
                status, body = safe_call(handle_kb_delete, source)
                return self._send_json(status, body)
            return self._send_json(404, fail(ErrorCode.NOT_FOUND, f"未知路径：{path}"))
        except Exception as exc:  # noqa: BLE001
            return self._send_error(exc)
        finally:
            self._access_log(started)

    def do_POST(self) -> None:
        started = time.perf_counter()
        self.rid = begin_request(self.headers.get("X-Request-ID"))
        self._status = 0
        path = urlparse(self.path).path
        try:
            if path == "/api/kb/upload":
                # 文件上传：原始字节交给统一的 multipart 解析器
                body = self._read_body()
                status, envelope = safe_call(handle_upload, self.headers.get("Content-Type", ""), body)
                return self._send_json(status, envelope)

            payload = self._read_json()
            if path == "/api/chat":
                status, body = safe_call(handle_chat, payload)
                return self._send_json(status, body)
            if path == "/api/chat/plan":
                status, body = safe_call(handle_chat_plan, payload)
                return self._send_json(status, body)
            if path == "/api/kb/ingest":
                status, body = safe_call(handle_ingest, payload)
                return self._send_json(status, body)
            if path == "/api/feedback":
                status, body = safe_call(handle_feedback, payload)
                return self._send_json(status, body)
            if path == "/api/chat/stream":
                _, events = handle_chat_stream(payload)  # 参数错误在这里抛出 -> 由外层兜底成 400
                return self._send_sse(events)
            return self._send_json(404, fail(ErrorCode.NOT_FOUND, f"未知路径：{path}"))
        except Exception as exc:  # noqa: BLE001
            return self._send_error(exc)
        finally:
            self._access_log(started)


def main():
    setup_logging()
    srv = ThreadingHTTPServer(("0.0.0.0", config.APP_PORT), Handler)
    print(f"Context Engine server running at http://localhost:{config.APP_PORT}")
    print(f"  UI:      http://localhost:{config.APP_PORT}/")
    print(f"  health:  http://localhost:{config.APP_PORT}/health")
    srv.serve_forever()


if __name__ == "__main__":
    main()
