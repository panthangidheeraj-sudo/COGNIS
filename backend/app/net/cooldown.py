"""A short memory of sources that just proved unreachable, so research does not wait on the same dead source again and again.

Only for *unreachable* answers (timeout, network error, 5xx) — never for "no data", which says nothing about the source being down. The memory is
per ``HttpClient`` (one per API process / test), expires by itself, and is cleared by the first good answer.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Cooling:
    classification: str  # the original failure class (timeout, network, server_error), so callers report the real reason
    reason: str
    seconds_left: float


class Cooldowns:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._until: dict[str, tuple[float, str, str]] = {}
        self._streak: dict[str, int] = {}

    def cooling(self, key: str) -> Cooling | None:
        entry = self._until.get(key)
        if entry is None:
            return None
        until, classification, reason = entry
        left = until - self._clock()
        if left <= 0:
            self._until.pop(key, None)
            return None
        return Cooling(classification, reason, left)

    def trip(self, key: str, seconds: float, classification: str, reason: str) -> None:
        if seconds > 0:
            self._until[key] = (self._clock() + seconds, classification, reason)

    def failure(self, key: str, *, threshold: int, seconds: float, classification: str, reason: str) -> bool:
        """Count one unreachable answer; opens the cooldown once ``threshold`` have come in a row. True when it is open."""
        self._streak[key] = self._streak.get(key, 0) + 1
        if self._streak[key] >= max(1, threshold):
            self.trip(key, seconds, classification, reason)
        return self.cooling(key) is not None

    def success(self, key: str) -> None:
        self._streak.pop(key, None)
        self._until.pop(key, None)
