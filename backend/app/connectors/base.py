"""Connector contract.

A connector turns one source request into a classified ``ModuleResult``.
Connectors never raise to the orchestrator and never decide publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..config import Settings, get_settings
from ..evidence.models import CLASSIFICATION_TO_AVAILABILITY, ModuleResult, Tier
from ..net.http import FetchResult, HttpClient
from ..runtime.budgets import CompanyBudget, RunBudget

SourceHealthState = Literal["healthy", "degraded", "blocked", "not_configured", "unsupported"]


@dataclass
class ConnectorContext:
    org_number: str
    http: HttpClient
    budget: CompanyBudget | RunBudget | None
    run_id: str | None = None
    settings: Settings = field(default_factory=get_settings)
    fresh: bool = False  # bypass cache (forced refresh)

    async def fetch(self, url: str, *, connector: str, **kwargs: Any) -> FetchResult:
        kwargs.setdefault("run_id", self.run_id)
        kwargs.setdefault("org_number", self.org_number)
        if self.fresh:
            kwargs["use_cache"] = False
        return await self.http.fetch(url, connector=connector, budget=self.budget, **kwargs)


class SourceConnector(Protocol):
    id: str
    name: str
    capabilities: set[str]

    def health(self) -> SourceHealthState: ...


def module_from_fetch(
    module: str,
    *,
    source_id: str,
    source_name: str,
    source_class: str,
    result: FetchResult,
    value: Any = None,
    raw: Any = None,
    tier: Tier = "A",
    note: str | None = None,
    effective_at: str | None = None,
) -> ModuleResult:
    state = CLASSIFICATION_TO_AVAILABILITY.get(result.classification, "failed")
    if result.classification == "budget_exhausted":
        note = note or "budget_exhausted"
    elif result.classification == "robots_disallowed":
        note = note or "disallowed by robots.txt"
    elif result.classification in ("not_found", "gone"):
        note = note or ("no record returned (HTTP 410: removed)" if result.classification == "gone" else "no record returned by the source")
    elif state == "failed":
        note = note or (result.error or result.classification)
    elif state == "blocked" and not note:
        note = result.error or "the source refused access"
    return ModuleResult(
        module=module,
        source_id=source_id,
        source_name=source_name,
        source_class=source_class,
        state=state,
        url=result.url,
        final_url=result.final_url,
        retrieved_at=result.retrieved_at,
        effective_at=effective_at or getattr(result, "effective_at", None),
        content_sha256=result.content_sha256,
        http_status=result.status or None,
        classification=result.classification,
        note=note,
        value=value,
        raw=raw,
        requests=0 if result.from_cache else 1 + result.retries + result.redirects,
        duration_ms=result.elapsed_ms,
        from_cache=result.from_cache,
        tier=tier,
    )


def not_run(module: str, *, source_id: str, source_name: str, source_class: str, state: str, note: str, url: str | None = None, tier: Tier = "A") -> ModuleResult:
    """A module that was deliberately not called (not applicable / not configured / skipped by plan)."""
    return ModuleResult(module=module, source_id=source_id, source_name=source_name, source_class=source_class, state=state, url=url, note=note, tier=tier)  # type: ignore[arg-type]
