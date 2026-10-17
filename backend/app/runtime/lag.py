"""Event-loop lag watchdog.

A batch runs every company on one asyncio loop. If the loop is blocked (a synchronous call, or the whole process paused), no timer can fire: the
per-company limits then cannot trip and every in-flight company simply looks slow. The monitor measures how late its own short sleeps wake up, so a
report can say "the loop stalled for N seconds" instead of leaving a slow run to be explained by guesswork. It changes no behaviour.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..core.util import now_iso


class LoopLagMonitor:
    def __init__(self, *, interval: float = 0.25, stall_seconds: float = 5.0, max_stalls: int = 20) -> None:
        self.interval = interval
        self.stall_seconds = stall_seconds
        self.max_stalls = max_stalls
        self.max_lag = 0.0
        self.total_stalled = 0.0
        self.stalls: list[dict[str, Any]] = []
        self._task: asyncio.Task[None] | None = None

    async def _watch(self) -> None:
        while True:
            before = time.monotonic()
            await asyncio.sleep(self.interval)
            lag = time.monotonic() - before - self.interval
            self.max_lag = max(self.max_lag, lag)
            if lag >= self.stall_seconds:
                self.total_stalled += lag
                if len(self.stalls) < self.max_stalls:
                    self.stalls.append({"ended_at": now_iso(), "seconds": round(lag, 1)})

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._watch())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def report(self) -> dict[str, Any]:
        return {"max_ms": int(self.max_lag * 1000), "stalls_over_threshold": len(self.stalls), "stalled_seconds": round(self.total_stalled, 1),
                "threshold_seconds": self.stall_seconds, "stalls": list(self.stalls)}
