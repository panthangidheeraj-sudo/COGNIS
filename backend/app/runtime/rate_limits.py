"""Per-host politeness: bounded concurrency + minimum spacing between request starts."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from ..config import get_settings


class HostLimiter:
    def __init__(self, default_concurrency: int | None = None):
        s = get_settings()
        self.default_concurrency = default_concurrency or s.host_concurrency
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._intervals: dict[str, float] = {}
        self._last_start: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._overrides: dict[str, int] = {"data.brreg.no": s.brreg_concurrency, "ws.geonorge.no": 4, "api.tavily.com": 2}

    def set_min_interval(self, key: str, seconds: float) -> None:
        self._intervals[key] = seconds

    def _sem(self, key: str) -> asyncio.Semaphore:
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(self._overrides.get(key, self.default_concurrency))
        return self._semaphores[key]

    @asynccontextmanager
    async def slot(self, host: str, interval_key: str | None = None):
        sem = self._sem(host)
        async with sem:
            key = interval_key or host
            interval = self._intervals.get(key, 0.0)
            if interval > 0:
                lock = self._locks.setdefault(key, asyncio.Lock())
                async with lock:
                    wait = interval - (time.monotonic() - self._last_start.get(key, 0.0))
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._last_start[key] = time.monotonic()
            yield
