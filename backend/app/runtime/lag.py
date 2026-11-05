"""Event-loop lag watchdog.

A batch runs every company on one asyncio loop. If the loop is blocked (a synchronous call, or the whole process paused), no timer can fire: the
per-company limits then cannot trip and every in-flight company simply looks slow. The monitor measures how late its own short sleeps wake up, so a
report can say "the loop stalled for N seconds" instead of leaving a slow run to be explained by guesswork. It changes no behaviour.

For each stall it also says *what kind* of stall it was and, where possible, *where*:

* ``cpu_seconds`` / ``cpu_share``  process CPU time used while the loop was stalled. A share near 1 means synchronous Python code was computing; a share near 0
                                   means the loop was blocked in I/O, sleeping, or the whole process was suspended (laptop sleep, a frozen console, a security scan).
* ``stack``                        the loop thread's call stack, sampled by a watchdog *thread* while the loop was still blocked (the loop itself cannot report
                                   what blocks it). ``top_frame`` is the innermost frame. Absent when the process was suspended, because the watchdog is suspended too.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
import traceback
from typing import Any

from ..core.util import now_iso

MAX_STACK_FRAMES = 25
MAX_SAMPLES_PER_STALL = 3
CPU_BOUND_SHARE = 0.6


def _short(path: str) -> str:
    """A path without the machine's directory layout: relative to ``backend/`` for project files, the last three parts otherwise."""
    parts = path.replace("\\", "/").split("/")
    if "backend" in parts:
        return "/".join(parts[len(parts) - parts[::-1].index("backend"):])
    return "/".join(parts[-3:])


def format_stack(frame: Any, limit: int = MAX_STACK_FRAMES) -> list[str]:
    """``["app/a.py:12 in f", …]``, outermost first, innermost last (the frame that was running)."""
    summary = traceback.extract_stack(frame)[-limit:]
    return [f"{_short(f.filename)}:{f.lineno} in {f.name}" for f in summary]


class LoopLagMonitor:
    def __init__(self, *, interval: float = 0.25, stall_seconds: float = 3.0, max_stalls: int = 20) -> None:
        self.interval = interval
        self.stall_seconds = stall_seconds
        self.max_stalls = max_stalls
        self.max_lag = 0.0
        self.total_stalled = 0.0
        self.stalls: list[dict[str, Any]] = []
        self._task: asyncio.Task[None] | None = None
        self._thread: threading.Thread | None = None
        self._stop_thread = threading.Event()
        self._lock = threading.Lock()
        self._loop_thread_id: int | None = None
        self._beat = time.monotonic()  # when the loop last proved it was running (written by the loop, read by the watchdog thread)
        self._beat_cpu = time.process_time()
        self._samples: list[list[str]] = []  # stacks of the loop thread sampled during the stall in progress

    # ------------------------------------------------------------------ loop side --
    async def _watch(self) -> None:
        while True:
            before = time.monotonic()
            await asyncio.sleep(self.interval)
            now = time.monotonic()
            lag = now - before - self.interval
            self.max_lag = max(self.max_lag, lag)
            cpu_now = time.process_time()
            with self._lock:
                samples, self._samples = self._samples, []
                cpu_used = cpu_now - self._beat_cpu
                self._beat, self._beat_cpu = now, cpu_now
            if lag >= self.stall_seconds:
                self.total_stalled += lag
                if len(self.stalls) < self.max_stalls:
                    self.stalls.append(self._record(lag, cpu_used, samples))

    def _record(self, lag: float, cpu_used: float, samples: list[list[str]]) -> dict[str, Any]:
        share = min(1.0, cpu_used / (lag + self.interval)) if lag > 0 else 0.0
        entry: dict[str, Any] = {"ended_at": now_iso(), "seconds": round(lag, 1), "cpu_seconds": round(cpu_used, 2), "cpu_share": round(share, 2),
                                 "kind": "cpu_bound" if share >= CPU_BOUND_SHARE else "blocked_or_suspended"}
        if samples:
            entry["stack"] = samples[-1]
            entry["top_frame"] = samples[-1][-1] if samples[-1] else None
            if len(samples) > 1:  # the stall outlived several samples: the frames that were running at each, so a slow loop and a stuck call can be told apart
                entry["top_frames_sampled"] = [s[-1] for s in samples if s]
        else:
            entry["stack"] = []
            entry["top_frame"] = None
            entry["note"] = "no stack was captured: the watchdog thread did not run during the stall, which points to a suspended process rather than slow code"
        return entry

    # ---------------------------------------------------------------- thread side --
    def _sample_loop(self) -> None:
        """Runs on its own thread: while the loop is overdue, record where the loop thread currently is."""
        poll = max(0.02, min(0.25, self.stall_seconds / 4))
        while not self._stop_thread.wait(poll):
            with self._lock:
                beat, taken = self._beat, len(self._samples)
            if taken >= MAX_SAMPLES_PER_STALL or time.monotonic() - beat < self.stall_seconds * (taken + 1):
                continue
            frame = sys._current_frames().get(self._loop_thread_id or -1)
            if frame is None:
                continue
            stack = format_stack(frame)
            with self._lock:
                if self._beat == beat:  # the loop did not recover while the stack was being read
                    self._samples.append(stack)

    # ------------------------------------------------------------------ lifecycle --
    def start(self) -> None:
        if self._task is None:
            self._loop_thread_id = threading.get_ident()
            self._beat, self._beat_cpu = time.monotonic(), time.process_time()
            self._stop_thread.clear()
            self._thread = threading.Thread(target=self._sample_loop, name="loop-lag-watchdog", daemon=True)
            self._thread.start()
            self._task = asyncio.get_running_loop().create_task(self._watch())

    async def stop(self) -> None:
        task, self._task = self._task, None
        self._stop_thread.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def report(self) -> dict[str, Any]:
        return {"max_ms": int(self.max_lag * 1000), "stalls_over_threshold": len(self.stalls), "stalled_seconds": round(self.total_stalled, 1),
                "threshold_seconds": self.stall_seconds, "stalls": list(self.stalls)}
