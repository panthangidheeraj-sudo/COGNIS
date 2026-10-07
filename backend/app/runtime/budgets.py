"""Central request / cost / time budget manager.

A ``RunBudget`` owns the hard limits for a whole run; ``CompanyBudget`` is a
child that also enforces per-company limits so one pathological company can't
consume the run. Every network request and every LLM call is charged here
*before* it happens (``reserve``) — nothing bypasses the budget.

Mandatory spend (identity anchoring) may use the budget up to the hard limit;
optional enrichment stops at ``headroom`` (default 90%) and when the time left
reaches the finalisation reserve. Running out never drops a company: the
affected modules are reported as ``blocked`` with reason ``budget_exhausted``.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class BudgetLimits:
    max_requests: int | None = None
    max_cost_usd: float | None = None
    max_runtime_seconds: float | None = None
    headroom: float = 0.9
    finalize_reserve_seconds: float = 30.0


@dataclass
class Spend:
    requests: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    llm_tokens: int = 0
    cache_hits: int = 0
    by_connector: Counter = field(default_factory=Counter)
    cost_by_connector: Counter = field(default_factory=Counter)
    blocked: Counter = field(default_factory=Counter)


class RunBudget:
    def __init__(self, limits: BudgetLimits, *, clock=time.monotonic):
        self.limits = limits
        self._clock = clock
        self.started = clock()
        self.spend = Spend()
        self._lock = threading.Lock()
        self.planned = Counter()  # planned-vs-executed accounting

    # ------------------------------------------------------------- time ----
    def elapsed(self) -> float:
        return self._clock() - self.started

    def remaining_seconds(self) -> float:
        if self.limits.max_runtime_seconds is None:
            return float("inf")
        return self.limits.max_runtime_seconds - self.elapsed()

    def time_for_optional(self) -> bool:
        return self.remaining_seconds() > self.limits.finalize_reserve_seconds

    # ------------------------------------------------------------- checks --
    def _fraction(self, optional: bool) -> float:
        return self.limits.headroom if optional else 1.0

    def can_spend(self, *, requests: int = 1, cost_usd: float = 0.0, optional: bool = True) -> bool:
        with self._lock:
            return self._can_spend_locked(requests, cost_usd, optional)

    def _can_spend_locked(self, requests: int, cost_usd: float, optional: bool) -> bool:
        fraction = self._fraction(optional)
        if self.limits.max_requests is not None and self.spend.requests + requests > self.limits.max_requests * fraction:
            return False
        if self.limits.max_cost_usd is not None and self.spend.cost_usd + cost_usd > self.limits.max_cost_usd * fraction + 1e-12:
            return False
        if self.limits.max_runtime_seconds is not None:
            reserve = self.limits.finalize_reserve_seconds if optional else self.limits.finalize_reserve_seconds / 3
            if self.remaining_seconds() <= reserve:
                return False
        return True

    def reserve(self, *, connector: str, requests: int = 1, cost_usd: float = 0.0, optional: bool = True) -> bool:
        """Atomically check and charge. Returns False (and records a block) when over budget."""
        with self._lock:
            if not self._can_spend_locked(requests, cost_usd, optional):
                self.spend.blocked[connector] += 1
                return False
            self.spend.requests += requests
            self.spend.cost_usd += cost_usd
            self.spend.by_connector[connector] += requests
            if cost_usd:
                self.spend.cost_by_connector[connector] += cost_usd
            return True

    def refund(self, *, connector: str, requests: int = 1, cost_usd: float = 0.0) -> None:
        """Return a reservation that never reached the network (cache hit, URL rejected)."""
        with self._lock:
            self.spend.requests = max(0, self.spend.requests - requests)
            self.spend.cost_usd = max(0.0, self.spend.cost_usd - cost_usd)
            self.spend.by_connector[connector] = max(0, self.spend.by_connector[connector] - requests)
            if cost_usd:
                self.spend.cost_by_connector[connector] = max(0.0, self.spend.cost_by_connector[connector] - cost_usd)

    def record_llm(self, *, tokens: int = 0, cost_usd: float = 0.0) -> None:
        with self._lock:
            self.spend.llm_calls += 1
            self.spend.llm_tokens += tokens
            self.spend.cost_usd += cost_usd
            if cost_usd:
                self.spend.cost_by_connector["llm"] += cost_usd

    def record_cache_hit(self) -> None:
        with self._lock:
            self.spend.cache_hits += 1

    def plan(self, connector: str, requests: int) -> None:
        with self._lock:
            self.planned[connector] += requests

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests": self.spend.requests,
                "third_party_cost_usd": round(self.spend.cost_usd, 6),
                "llm_calls": self.spend.llm_calls,
                "llm_tokens": self.spend.llm_tokens,
                "cache_hits": self.spend.cache_hits,
                "elapsed_seconds": round(self.elapsed(), 3),
                "requests_by_connector": dict(self.spend.by_connector),
                "cost_by_connector": {k: round(v, 6) for k, v in self.spend.cost_by_connector.items()},
                "blocked_by_budget": dict(self.spend.blocked),
                "planned_requests": dict(self.planned),
                "limits": {
                    "max_requests": self.limits.max_requests,
                    "max_cost_usd": self.limits.max_cost_usd,
                    "max_runtime_seconds": self.limits.max_runtime_seconds,
                    "headroom": self.limits.headroom,
                },
            }


class CompanyBudget:
    """Per-company limits layered on top of the run budget."""

    def __init__(self, run: RunBudget, *, max_requests: int, max_seconds: float, max_llm_calls: int, max_searches: int, clock=time.monotonic):
        self.run = run
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self.max_llm_calls = max_llm_calls
        self.max_searches = max_searches
        self._clock = clock
        self.started = clock()
        self.requests = 0
        self.cost_usd = 0.0
        self.llm_calls = 0
        self.searches = 0
        self.by_connector: Counter = Counter()
        self.blocked: Counter = Counter()
        self._lock = threading.Lock()

    def elapsed(self) -> float:
        return self._clock() - self.started

    def deadline_left(self) -> float:
        return min(self.max_seconds - self.elapsed(), self.run.remaining_seconds() - self.run.limits.finalize_reserve_seconds / 3)

    def can_optional(self) -> bool:
        return self.deadline_left() > 2 and self.requests < self.max_requests and self.run.time_for_optional()

    def reserve(self, *, connector: str, requests: int = 1, cost_usd: float = 0.0, optional: bool = True, search: bool = False) -> bool:
        with self._lock:
            if optional and (self.requests + requests > self.max_requests or self.deadline_left() <= 1):
                self.blocked[connector] += 1
                return False
            if search and self.searches >= self.max_searches:
                self.blocked[connector] += 1
                return False
        if not self.run.reserve(connector=connector, requests=requests, cost_usd=cost_usd, optional=optional):
            with self._lock:
                self.blocked[connector] += 1
            return False
        with self._lock:
            self.requests += requests
            self.cost_usd += cost_usd
            self.by_connector[connector] += requests
            if search:
                self.searches += 1
        return True

    def refund(self, *, connector: str, requests: int = 1, cost_usd: float = 0.0, search: bool = False) -> None:
        self.run.refund(connector=connector, requests=requests, cost_usd=cost_usd)
        with self._lock:
            self.requests = max(0, self.requests - requests)
            self.cost_usd = max(0.0, self.cost_usd - cost_usd)
            self.by_connector[connector] = max(0, self.by_connector[connector] - requests)
            if search:
                self.searches = max(0, self.searches - 1)

    def allow_llm(self) -> bool:
        with self._lock:
            return self.llm_calls < self.max_llm_calls and self.deadline_left() > 5

    def record_llm(self, *, tokens: int, cost_usd: float) -> None:
        with self._lock:
            self.llm_calls += 1
            self.cost_usd += cost_usd
        self.run.record_llm(tokens=tokens, cost_usd=cost_usd)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests": self.requests,
                "third_party_cost_usd": round(self.cost_usd, 6),
                "llm_calls": self.llm_calls,
                "searches": self.searches,
                "runtime_ms": int(self.elapsed() * 1000),
                "requests_by_connector": dict(self.by_connector),
                "blocked_by_budget": dict(self.blocked),
            }


def unlimited_budget() -> RunBudget:
    """Budget for interactive API use: generous but still bounded."""
    from ..config import get_settings

    s = get_settings()
    return RunBudget(BudgetLimits(max_requests=None, max_cost_usd=s.max_external_cost_usd, max_runtime_seconds=None, headroom=1.0, finalize_reserve_seconds=0))
