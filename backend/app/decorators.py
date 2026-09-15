"""装饰器：耗时统计 / 失败重试 / 结果缓存。

装饰器 / 生成器 / 异步的机制说明——
这里不是玩具例子，三个装饰器都在真实链路上：

* ``@timed``         → Agent 节点与工具调用，耗时进日志，并写进本次请求的
  timing 收集器（前端「看板」页画节点耗时柱状图用的就是它）。
* ``@retry``         → 调用外部服务（天气 API、大模型 API）的失败重试，
  指数退避；重试次数与最终失败都写日志。
* ``@cache_result``  → 缓存读多写少的聚合查询（看板统计）。

都是"带参数的装饰器"（多一层闭包），并且用 ``functools.wraps`` 保留元信息。
"""
from __future__ import annotations

import contextvars
import functools
import time
from typing import Any, Callable, Optional

from .logging_config import get_logger, log
import logging

_logger = get_logger("app.decorators")

#: 本次请求内被 @timed 记录下来的耗时；由 timing_scope() 在请求入口重置。
_TIMINGS: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar("timings", default=None)


def timing_scope() -> list:
    """开一个耗时收集作用域，返回该列表（请求结束时读它）。"""
    lst: list = []
    _TIMINGS.set(lst)
    return lst


def current_timings() -> list:
    return _TIMINGS.get() or []


def timed(name: Optional[str] = None, *, level: int = logging.INFO) -> Callable:
    """记录函数耗时（毫秒）。"""

    def deco(fn: Callable) -> Callable:
        label = name or fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                ms = (time.perf_counter() - t0) * 1000
                bucket = _TIMINGS.get()
                if bucket is not None:
                    bucket.append({"name": label, "ms": round(ms, 1)})
                log(_logger, level, "timed", func=label, ms=round(ms, 1))

        return wrapper

    return deco


def retry(
    times: int = 2,
    *,
    delay: float = 0.2,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """失败重试（指数退避）。``times`` 是总尝试次数。"""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            wait = delay
            last: Optional[BaseException] = None
            for attempt in range(1, max(1, times) + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203 - 重试逻辑本身需要 try/except
                    last = exc
                    if attempt >= times:
                        break
                    log(
                        _logger,
                        logging.WARNING,
                        "retry",
                        func=fn.__qualname__,
                        attempt=attempt,
                        error=exc.__class__.__name__,
                        wait=round(wait, 2),
                    )
                    time.sleep(wait)
                    wait *= backoff
            log(_logger, logging.ERROR, "retry_give_up", func=fn.__qualname__, attempts=times)
            raise last  # type: ignore[misc]

        return wrapper

    return deco


def cache_result(ttl: Optional[int] = None, *, key_builder: Optional[Callable] = None) -> Callable:
    """把返回值放进应用的缓存后端（默认进程内 LRU，配了 REDIS_URL 就是 Redis）。

    缓存值必须是可 JSON 序列化的（同一套代码要同时兼容两种后端）。
    """

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            from .storage.cache import get_cache

            cache = get_cache()
            if key_builder is not None:
                key = key_builder(*args, **kwargs)
            else:
                parts = [repr(a) for a in args[1:]] + [f"{k}={v!r}" for k, v in sorted(kwargs.items())]
                key = f"fn:{fn.__qualname__}:" + "|".join(parts)
            hit = cache.get(key)
            if hit is not None:
                log(_logger, logging.DEBUG, "cache_hit", func=fn.__qualname__)
                return hit
            value = fn(*args, **kwargs)
            try:
                cache.set(key, value, ttl=ttl)
            except Exception:  # 缓存失败不能影响主流程
                log(_logger, logging.WARNING, "cache_set_failed", func=fn.__qualname__)
            return value

        return wrapper

    return deco
