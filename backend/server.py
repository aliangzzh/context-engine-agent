"""Zero-dependency HTTP server (stdlib only) that runs the demo right now.

Serves the static single-file UI at ``/`` and the JSON / SSE API under ``/api``.
No pip install required (uses the stdlib ``http.server``; the app logic needs
only pydantic / python-dotenv / requests, all present on the base interpreter).

Optional upgrade path: ``pip install fastapi uvicorn`` and run ``app/main.py``
(the FastAPI reference implementation) against the same ``app/api.py`` handlers.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app import config
from app.api import (
    handle_chat, handle_chat_plan, handle_chat_stream,
    handle_context, handle_health, handle_ingest,
)

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
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, code: int, body) -> None:
        data = json.dumps(_jsonable(body), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _send_file(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self._cors()
        ct = "text/html; charset=utf-8" if path.suffix == ".html" else "application/octet-stream"
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, events) -> None:
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for evt in events:
            chunk = f"data: {json.dumps(_jsonable(evt), ensure_ascii=False)}\n\n".encode("utf-8")
            self.wfile.write(chunk)
            self.wfile.flush()

    def log_message(self, fmt, *args):  # keep console quiet
        return

    # --- HTTP methods -------------------------------------------------------------
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            return self._send_json(*handle_health())
        if path.startswith("/api/context/"):
            sid = path.rsplit("/", 1)[1]
            return self._send_json(*handle_context(sid))
        if path == "/" or path == "/index.html":
            index = STATIC_DIR / "index.html"
            if index.exists():
                return self._send_file(index)
            return self._send_json(200, {"message": "static UI not found", "static_dir": str(STATIC_DIR)})
        return self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/api/chat":
            return self._send_json(*handle_chat(payload))
        if path == "/api/chat/plan":
            return self._send_json(*handle_chat_plan(payload))
        if path == "/api/kb/ingest":
            return self._send_json(*handle_ingest(payload))
        if path == "/api/chat/stream":
            return self._send_sse(handle_chat_stream(payload)[1])
        return self._send_json(404, {"error": "not found"})


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", config.APP_PORT), Handler)
    print(f"Context Engine server running at http://localhost:{config.APP_PORT}")
    print(f"  UI:      http://localhost:{config.APP_PORT}/")
    print(f"  health:  http://localhost:{config.APP_PORT}/health")
    srv.serve_forever()


if __name__ == "__main__":
    main()
