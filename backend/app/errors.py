"""统一错误码 + 业务异常 + 统一响应体。

错误码的设计取舍：
* HTTP 状态码表达"传输/语义层面"的结果，``code`` 表达"业务层面"的结果，
  两者分开，前端才能按 code 做分支，而不是靠字符串匹配 message。
* 错误码按段位划分：40xxx 客户端、50xxx 服务端、502xx 上游（模型/检索）——
  新增错误只加枚举，不改调用方。
"""
from __future__ import annotations

from enum import IntEnum
from typing import Any, Optional


class ErrorCode(IntEnum):
    OK = 0

    # 40xxx：调用方的问题
    BAD_REQUEST = 40000
    VALIDATION_ERROR = 40001
    NOT_FOUND = 40400
    PAYLOAD_TOO_LARGE = 41300
    UNSUPPORTED_MEDIA = 41500
    RATE_LIMITED = 42900

    # 50xxx：服务端的问题
    INTERNAL_ERROR = 50000
    DB_ERROR = 50001
    STORAGE_ERROR = 50002
    # 502xx：依赖的上游（大模型 / 向量检索 / 外部工具）
    UPSTREAM_ERROR = 50200
    MODEL_ERROR = 50201


#: 业务错误码 -> 默认 HTTP 状态码
_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.OK: 200,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_MEDIA: 415,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.DB_ERROR: 500,
    ErrorCode.STORAGE_ERROR: 500,
    ErrorCode.UPSTREAM_ERROR: 502,
    ErrorCode.MODEL_ERROR: 502,
}


def _coerce(code: "ErrorCode | int") -> ErrorCode:
    return code if isinstance(code, ErrorCode) else ErrorCode(code)


class AppError(Exception):
    """业务异常。带错误码抛出，由统一的异常处理转成响应体。"""

    def __init__(
        self,
        code: "ErrorCode | int",
        msg: str,
        *,
        detail: Any = None,
        http_status: Optional[int] = None,
    ):
        super().__init__(msg)
        self.code = _coerce(code)
        self.msg = msg
        self.detail = detail
        self.http_status = http_status or _HTTP_STATUS.get(self.code, 500)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"AppError(code={int(self.code)}, msg={self.msg!r})"


def ok(data: Any = None, msg: str = "ok") -> dict:
    """成功响应体：``{code:0, msg, data}``。"""
    return {"code": int(ErrorCode.OK), "msg": msg, "data": data}


def fail(code: "ErrorCode | int", msg: str, detail: Any = None) -> dict:
    """失败响应体：``{code, msg, data:null, detail?}``。"""
    c = _coerce(code)
    body: dict = {"code": int(c), "msg": msg, "data": None}
    if detail is not None:
        body["detail"] = detail
    return body


def error_from_exception(exc: BaseException) -> tuple[int, dict]:
    """把任意异常映射成 ``(http_status, 响应体)``。

    * ``AppError``          -> 它自带的错误码
    * pydantic 校验失败     -> 40001（并给出字段级 detail，方便前端表单回填）
    * 其它未预期异常        -> 50000（不把堆栈泄露给调用方，只写日志）
    """
    if isinstance(exc, AppError):
        return exc.http_status, fail(exc.code, exc.msg, exc.detail)

    if exc.__class__.__name__ == "ValidationError":  # pydantic v2
        detail = None
        errors = getattr(exc, "errors", None)
        if callable(errors):
            try:
                detail = [
                    {"field": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
                    for e in errors()
                ]
            except Exception:  # pragma: no cover - defensive
                detail = str(exc)[:300]
        return 400, fail(ErrorCode.VALIDATION_ERROR, "参数校验失败", detail)

    if isinstance(exc, ValueError):
        return 400, fail(ErrorCode.BAD_REQUEST, str(exc) or "非法请求")

    return 500, fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误")
