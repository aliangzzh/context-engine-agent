"""极简 multipart/form-data 解析（stdlib，不依赖 python-multipart）。

为什么自己写：FastAPI 的 ``UploadFile`` 需要 ``python-multipart``；stdlib 版
``server.py`` 更是没有任何表单解析。项目要求"零依赖也能跑"，所以这里实现一个
够用的解析器（浏览器 ``<input type=file>`` / ``FormData`` 的常规格式），
两个 HTTP 入口（``server.py`` 与 ``app/main.py``）共用同一份代码。

支持：普通字段 + 单文件/多文件；超过 ``max_bytes`` 抛 ``AppError(41300)``。
不支持（用不到）：嵌套 multipart、``Content-Transfer-Encoding``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .errors import AppError, ErrorCode

#: 单文件上传上限（可被调用方覆盖）
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


@dataclass
class UploadedFile:
    field: str
    filename: str
    content_type: str = "application/octet-stream"
    data: bytes = b""

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def text(self) -> str:
        return self.data.decode("utf-8-sig", errors="ignore")


@dataclass
class MultipartForm:
    fields: dict = field(default_factory=dict)
    files: list = field(default_factory=list)

    def first_file(self) -> Optional[UploadedFile]:
        return self.files[0] if self.files else None


def _boundary_of(content_type: str) -> str:
    if "multipart/form-data" not in (content_type or "").lower():
        raise AppError(
            ErrorCode.UNSUPPORTED_MEDIA,
            "需要 multipart/form-data 请求",
            detail={"content_type": content_type},
        )
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            return part.split("=", 1)[1].strip().strip('"')
    raise AppError(ErrorCode.BAD_REQUEST, "multipart 缺少 boundary")


def _parse_disposition(value: str) -> dict:
    """``form-data; name="f"; filename="a.txt"`` -> {name, filename}"""
    out: dict = {}
    for seg in value.split(";"):
        seg = seg.strip()
        if "=" in seg:
            k, v = seg.split("=", 1)
            out[k.strip().lower()] = v.strip().strip('"')
    return out


def parse_multipart(content_type: str, body: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES) -> MultipartForm:
    if len(body) > max_bytes:
        raise AppError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"上传内容超过上限 {max_bytes // 1024} KB",
            detail={"size": len(body), "limit": max_bytes},
        )
    boundary = _boundary_of(content_type).encode("utf-8")
    delimiter = b"--" + boundary
    form = MultipartForm()

    for raw in body.split(delimiter):
        if not raw or raw in (b"--", b"--\r\n", b"\r\n"):
            continue
        raw = raw.lstrip(b"\r\n")
        if raw.startswith(b"--"):  # 结束标记
            continue
        head, sep, content = raw.partition(b"\r\n\r\n")
        if not sep:
            continue
        content = content[:-2] if content.endswith(b"\r\n") else content  # 去掉分隔前的 CRLF

        headers: dict = {}
        for line in head.decode("utf-8", errors="ignore").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        disp = _parse_disposition(headers.get("content-disposition", ""))
        name = disp.get("name", "")
        filename = disp.get("filename")
        if filename is not None:
            form.files.append(
                UploadedFile(
                    field=name,
                    filename=filename,
                    content_type=headers.get("content-type", "application/octet-stream"),
                    data=content,
                )
            )
        elif name:
            form.fields[name] = content.decode("utf-8-sig", errors="ignore")

    return form
