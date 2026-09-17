"""接口测试：handler 层 + 真实 HTTP 层（stdlib urllib 打 stdlib server）。

接口测试，以及「接口通了但页面没显示」的排查：
* handler 层直接断言统一响应体 ``{code,msg,data}`` 与错误码；
* HTTP 层真的起一个服务器再发请求，验证状态码/头/分页/上传/错误码，
  所以前端的联调问题在这里就能先暴露一次。

不需要 httpx/requests 之外的依赖（这里连 requests 都不用，纯 urllib）。
"""
import json
import os
import shutil
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app import api, config
from app.errors import AppError, ErrorCode, error_from_exception
from app.multipart import parse_multipart
from server import Handler  # backend/server.py（stdlib 零依赖入口）

_SCRATCH = Path(__file__).parent / "_scratch"


def _scratch_dir() -> Path:
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    d = _SCRATCH / f"api_{os.getpid()}_{threading.get_ident()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _multipart(fields: dict, filename: str, content: bytes, field_name: str = "file") -> tuple[str, bytes]:
    """拼一个 multipart/form-data 请求体（浏览器 FormData 的等价物）。"""
    boundary = "----ctxengineboundary1234"
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n\r\n".encode() + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


class _IsolatedServices(unittest.TestCase):
    """把数据目录换到临时目录，避免污染开发库 / 用例之间互相干扰。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = _scratch_dir()
        cls._orig = {k: getattr(config, k) for k in ("DATA_DIR", "KB_DIR", "DB_PATH")}
        config.DATA_DIR = cls.tmp / "data"
        config.KB_DIR = config.DATA_DIR / "kb"
        config.DB_PATH = config.DATA_DIR / "app.db"
        api.reset_services()

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._orig.items():
            setattr(config, k, v)
        api.reset_services()
        shutil.rmtree(cls.tmp, ignore_errors=True)


class HandlerTest(_IsolatedServices):
    def test_health_envelope(self):
        status, body = api.handle_health()
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["db_backend"], "sqlite")
        self.assertEqual(body["data"]["cache_backend"], "lru")

    def test_chat_returns_unified_envelope(self):
        status, body = api.handle_chat({"message": "身高170厘米体重110斤穿什么尺码？", "session_id": "t1"})
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)
        self.assertTrue(body["data"]["answer"])
        self.assertIn("context", body["data"])
        self.assertIn("agent_trace", body["data"])

    def test_missing_message_maps_to_validation_code(self):
        status, body = api.safe_call(api.handle_chat, {"session_id": "t1"})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], int(ErrorCode.VALIDATION_ERROR))
        self.assertIsNone(body["data"])
        self.assertTrue(any(d["field"].endswith("message") for d in body["detail"]))

    def test_kb_list_pagination(self):
        status, body = api.handle_kb_list({"page": 1, "size": 2})
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["size"], 2)
        self.assertGreaterEqual(body["data"]["total"], 1)  # demo 知识库已注入
        self.assertLessEqual(len(body["data"]["items"]), 2)

    def test_kb_list_rejects_bad_page(self):
        for query in ({"page": 0}, {"size": 999}, {"page": "abc"}):
            status, body = api.safe_call(api.handle_kb_list, query)
            self.assertEqual(status, 400, query)
            self.assertEqual(body["code"], int(ErrorCode.VALIDATION_ERROR))

    def test_kb_delete_unknown_source_is_404(self):
        status, body = api.safe_call(api.handle_kb_delete, "根本不存在的文档.txt")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], int(ErrorCode.NOT_FOUND))

    def test_ingest_then_delete_source(self):
        status, body = api.handle_ingest({"text": "批量测试文档内容，用于删除用例。", "filename": "临时文档.txt"})
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["status"], "ingested")
        status, body = api.handle_kb_delete("临时文档.txt")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["data"]["deleted_chunks"], 1)

    def test_ingest_empty_text_rejected(self):
        status, body = api.safe_call(api.handle_ingest, {"text": "   "})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], int(ErrorCode.VALIDATION_ERROR))

    def test_upload_multipart(self):
        content_type, payload = _multipart({}, "上传测试.txt", "上传接口写入的知识：加绒牛仔水温不超过30度。".encode())
        status, body = api.handle_upload(content_type, payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "ingested")
        self.assertGreaterEqual(body["data"]["chunks"], 1)

    def test_upload_unsupported_type(self):
        content_type, payload = _multipart({}, "报告.pdf", b"%PDF-1.4 fake")
        status, body = api.handle_upload(content_type, payload)
        self.assertEqual(status, 415)
        self.assertEqual(body["code"], int(ErrorCode.UNSUPPORTED_MEDIA))

    def test_upload_without_file(self):
        # 只有普通字段、没有 file 字段
        content_type = "multipart/form-data; boundary=xx"
        payload = b'--xx\r\nContent-Disposition: form-data; name="note"\r\n\r\nhi\r\n--xx--\r\n'
        status, body = api.safe_call(api.handle_upload, content_type, payload)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], int(ErrorCode.VALIDATION_ERROR))

    def test_upload_wrong_content_type(self):
        status, body = api.safe_call(api.handle_upload, "application/json", b"{}")
        self.assertEqual(status, 415)
        self.assertEqual(body["code"], int(ErrorCode.UNSUPPORTED_MEDIA))

    def test_feedback_round_trip(self):
        status, body = api.handle_feedback({
            "session_id": "t1", "message": "退货怎么算？", "answer": "编造的回答",
            "reason": "hallucination", "note": "检索为空时硬答",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)
        status, listing = api.handle_feedback_list({"page": 1, "size": 5})
        self.assertGreaterEqual(listing["data"]["total"], 1)
        reasons = {d["reason"] for d in api.handle_stats()[1]["data"]["feedback"]["distribution"]}
        self.assertIn("hallucination", reasons)

    def test_feedback_invalid_reason(self):
        status, body = api.safe_call(api.handle_feedback, {
            "message": "q", "answer": "a", "reason": "随便写的",
        })
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], int(ErrorCode.VALIDATION_ERROR))

    def test_stats_shape(self):
        status, body = api.handle_stats()
        data = body["data"]
        self.assertEqual(status, 200)
        for key in ("kb", "feedback", "requests", "runtime"):
            self.assertIn(key, data)
        self.assertIn("chunk_strategy", data["runtime"])
        self.assertIn("series", data["requests"])

    def test_error_from_exception_mapping(self):
        status, body = error_from_exception(AppError(ErrorCode.NOT_FOUND, "没找到"))
        self.assertEqual((status, body["code"]), (404, int(ErrorCode.NOT_FOUND)))
        status, body = error_from_exception(ValueError("非法"))
        self.assertEqual((status, body["code"]), (400, int(ErrorCode.BAD_REQUEST)))
        status, body = error_from_exception(RuntimeError("炸了"))
        self.assertEqual((status, body["code"]), (500, int(ErrorCode.INTERNAL_ERROR)))
        # 未预期异常不能把内部信息泄露出去
        self.assertNotIn("炸了", json.dumps(body, ensure_ascii=False))

    def test_multipart_size_limit(self):
        with self.assertRaises(AppError) as ctx:
            parse_multipart("multipart/form-data; boundary=xx", b"x" * 10, max_bytes=5)
        self.assertEqual(ctx.exception.code, ErrorCode.PAYLOAD_TOO_LARGE)


class HttpTest(_IsolatedServices):
    """真起服务器：验证状态码、响应头、分页、上传、错误码。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        api.services()  # 预热（等价于进程启动后的第一个请求）
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def _request(self, method: str, path: str, body: bytes | None = None,
                 content_type: str = "application/json") -> tuple[int, dict, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), dict(exc.headers)

    def test_health_http(self):
        status, body, headers = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)
        self.assertIn("X-Request-ID", headers)

    def test_kb_list_http_pagination(self):
        status, body, _ = self._request("GET", "/api/kb/list?page=1&size=2")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["page"], 1)
        self.assertEqual(body["data"]["size"], 2)

    def test_kb_list_http_bad_params(self):
        status, body, _ = self._request("GET", "/api/kb/list?page=0")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], int(ErrorCode.VALIDATION_ERROR))

    def test_upload_http_multipart(self):
        content_type, payload = _multipart({}, "http上传.txt", "HTTP 上传的内容：春季适合薄荷绿。".encode())
        status, body, _ = self._request("POST", "/api/kb/upload", payload, content_type)
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["filename"], "http上传.txt")

    def test_feedback_http(self):
        payload = json.dumps({"message": "q", "answer": "a", "reason": "other"}).encode()
        status, body, _ = self._request("POST", "/api/feedback", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)

    def test_delete_http_urlencoded_chinese(self):
        api.handle_ingest({"text": "待删除文档内容", "filename": "待删除.txt"})
        path = "/api/kb/" + urllib.parse.quote("待删除.txt")
        status, body, _ = self._request("DELETE", path)
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["source"], "待删除.txt")

    def test_stats_http(self):
        status, body, _ = self._request("GET", "/api/stats")
        self.assertEqual(status, 200)
        self.assertIn("runtime", body["data"])

    def test_chat_http_missing_field_returns_400(self):
        status, body, _ = self._request("POST", "/api/chat", json.dumps({"session_id": "x"}).encode())
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], int(ErrorCode.VALIDATION_ERROR))

    def test_invalid_json_returns_400(self):
        status, body, _ = self._request("POST", "/api/chat", b"{oops")
        self.assertEqual(status, 400)

    def test_unknown_path_returns_404(self):
        status, body, _ = self._request("GET", "/api/nope")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], int(ErrorCode.NOT_FOUND))

    def test_static_ui_served(self):
        status, _, headers = self._request_raw("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))

    def _request_raw(self, method: str, path: str):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)

class UpstreamErrorTest(_IsolatedServices):
    """模型/上游失败必须报 502xx，而不是 50000（服务端自己的锅）。"""
    class _BrokenModel:
        name = "broken"
        def generate(self, messages):
            raise RuntimeError("model timeout after 30s")
        def stream(self, messages):
            raise RuntimeError("model timeout after 30s")
    def test_model_failure_reports_upstream_error(self):
        svc = api.services()
        saved = svc.model
        svc.model = self._BrokenModel()
        try:
            status, body = api.safe_call(api.handle_chat, {"message": "hi"})
        finally:
            svc.model = saved
        self.assertEqual(status, 502)
        self.assertEqual(body["code"], int(ErrorCode.MODEL_ERROR))
if __name__ == "__main__":
    unittest.main()
