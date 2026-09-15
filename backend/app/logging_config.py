"""日志：结构化输出 + request_id 贯穿 + 耗时统计。

异常处理与日志记录。设计取舍：
* 用 stdlib ``logging``（不引三方日志库），单进程 demo 足够；
* 输出 key=value 的单行文本，既好读又好被日志系统切分；
* ``request_id`` 放在 ``contextvars`` 里，任何一层拿 logger 都能带上它，
  不用把 request_id 参数层层传递；
* 绝不打印 ``DASHSCOPE_API_KEY`` 之类的密钥（``_redact`` 兜底）。
"""
from __future__ import annotations

import contextvars
import logging
import os
import sys
import time
import uuid
from typing import Any, Optional

#: 每请求一个 id，贯穿 API -> service -> storage 的所有日志
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_CONFIGURED = False


class _KVFormatter(logging.Formatter):
    """``2026-01-01 10:00:00 INFO  app.api  rid=ab12 msg="..." k=v``"""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} "
            f"{record.levelname:<5} {record.name:<22} rid={request_id_var.get()}"
        )
        extra = getattr(record, "extra_fields", None)
        tail = ""
        if extra:
            tail = " " + " ".join(f"{k}={_redact(k, v)}" for k, v in extra.items())
        return f"{base} {record.getMessage()}{tail}"


_SECRET_HINTS = ("key", "token", "secret", "password")


def _redact(name: str, value: Any) -> Any:
    if any(h in name.lower() for h in _SECRET_HINTS) and value:
        return "***"
    return value


def setup_logging(level: Optional[str] = None, *, force: bool = False) -> None:
    """初始化根 logger（重复调用是幂等的）。"""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    lvl = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_KVFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, lvl, logging.INFO))
    # 三方库降噪
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(rid: Optional[str] = None) -> str:
    rid = rid or new_request_id()
    request_id_var.set(rid)
    return rid


def log(logger: logging.Logger, level: int, text: str, **fields: Any) -> None:
    """带结构化字段的日志（字段会以 ``k=v`` 追加在行尾）。

    注意第一个位置参数不叫 ``msg``，否则调用方传 ``msg=...`` 当字段时会冲突。
    """
    if logger.isEnabledFor(level):
        logger.log(level, text, extra={"extra_fields": fields})


class timed_block:
    """上下文管理器版耗时统计：``with timed_block(logger, "kb.ingest", n=3):``"""

    def __init__(self, logger: logging.Logger, name: str, level: int = logging.INFO, **fields: Any):
        self.logger = logger
        self.name = name
        self.level = level
        self.fields = fields
        self.ms = 0.0

    def __enter__(self) -> "timed_block":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.ms = (time.perf_counter() - self._t0) * 1000
        fields = dict(self.fields, ms=round(self.ms, 1))
        if exc is not None:
            fields["error"] = exc.__class__.__name__
            log(self.logger, logging.ERROR, f"{self.name} failed", **fields)
        else:
            log(self.logger, self.level, self.name, **fields)
        return False  # 不吞异常
