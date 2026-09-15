"""进程内指标采集（看板数据源）。

单进程 demo 不需要 Prometheus；这里用一个线程安全的环形缓冲记录最近 N 次
请求的耗时 / token 占用 / 命中的工具，供「看板」页画图和排查用。
换成多实例部署时，把它替换成 Redis/时序库即可，接口保持 ``record/summary``。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


class MetricsRecorder:
    def __init__(self, size: int = 100):
        self._lock = threading.Lock()
        self._events: deque = deque(maxlen=size)
        self._counters: dict = {}

    def record(self, entry: dict) -> dict:
        entry = dict(entry)
        entry.setdefault("ts", time.strftime("%H:%M:%S"))
        entry.setdefault("epoch", time.time())
        with self._lock:
            self._events.append(entry)
            for key in entry.get("tools", []) or []:
                name = key.split("=>")[0].strip()
                self._counters[name] = self._counters.get(name, 0) + 1
        return entry

    def incr(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + n

    def recent(self, n: int = 20) -> list:
        with self._lock:
            items = list(self._events)
        return items[-n:]

    def summary(self) -> dict:
        with self._lock:
            events = list(self._events)
            counters = dict(self._counters)
        if not events:
            return {"requests": 0, "avg_ms": 0, "avg_tokens": 0, "p95_ms": 0,
                    "max_tokens": 0, "budget": 0, "tool_calls": counters, "series": []}
        latencies = sorted(e.get("elapsed_ms", 0) for e in events)
        idx = min(len(latencies) - 1, int(len(latencies) * 0.95))
        return {
            "requests": len(events),
            "avg_ms": round(sum(latencies) / len(latencies), 1),
            "p95_ms": latencies[idx],
            "avg_tokens": round(sum(e.get("tokens", 0) for e in events) / len(events), 1),
            "max_tokens": max(e.get("tokens", 0) for e in events),
            "budget": max((e.get("budget", 0) for e in events), default=0),
            "tool_calls": counters,
            "series": [
                {
                    "ts": e.get("ts", ""),
                    "tokens": e.get("tokens", 0),
                    "budget": e.get("budget", 0),
                    "ms": e.get("elapsed_ms", 0),
                    "over_budget": bool(e.get("over_budget")),
                }
                for e in events[-20:]
            ],
        }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._counters.clear()


_recorder: Optional[MetricsRecorder] = None
_lock = threading.Lock()


def get_metrics() -> MetricsRecorder:
    global _recorder
    with _lock:
        if _recorder is None:
            _recorder = MetricsRecorder()
        return _recorder
