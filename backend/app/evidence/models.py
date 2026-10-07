"""Core research data model: module results, snapshots and observations.

Flow: connector → ``ModuleResult`` (one fetched source response, classified)
→ extractor → ``Observation`` (a *candidate* fact with provenance)
→ publication gate → published claim / rejected observation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Availability = Literal["available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"]
AVAILABILITY_STATES: tuple[str, ...] = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")

Tier = Literal["A", "B", "C"]  # A primary/authoritative · B strong secondary · C discovery/context

# Fetch classification → availability for a module.
CLASSIFICATION_TO_AVAILABILITY: dict[str, Availability] = {
    "ok": "available",
    "not_found": "not_available",
    "gone": "not_available",
    "blocked": "blocked",
    "robots_disallowed": "blocked",
    "budget_exhausted": "blocked",
    "rate_limited": "blocked",
    "unsafe_url": "blocked",
    "server_error": "failed",
    "client_error": "failed",
    "timeout": "failed",
    "network": "failed",
    "too_large": "failed",
    "invalid_content": "failed",
}


@dataclass
class ModuleResult:
    module: str
    source_id: str
    source_name: str
    source_class: str
    state: Availability
    url: str | None = None
    final_url: str | None = None
    retrieved_at: str | None = None
    effective_at: str | None = None
    content_sha256: str | None = None
    http_status: int | None = None
    classification: str | None = None
    note: str | None = None
    value: Any = None  # normalised payload (persisted; drives change detection)
    raw: Any = None  # parsed raw payload (in memory only)
    requests: int = 0
    duration_ms: int = 0
    from_cache: bool = False
    tier: Tier = "A"

    def snapshot_meta(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


@dataclass
class Observation:
    """A candidate fact. Nothing is published without passing the gate."""

    field: str
    value: Any
    module: str
    source_id: str
    source_name: str
    source_class: str
    source_url: str | None
    retrieved_at: str | None
    content_sha256: str | None
    claim_span: str
    extraction_method: str
    tier: Tier = "A"
    label: str | None = None
    key_suffix: str | None = None  # distinguishes multi-valued fields (person, subunit, year …)
    reporting_period: str | None = None  # ISO interval "2025-01-01/2025-12-31"
    period_label: str | None = None  # "FY2025"
    effective_from: str | None = None
    effective_to: str | None = None
    as_of: str | None = None
    unit: str | None = None
    currency: str | None = None
    identity_score: float = 1.0
    identity_signals: list[str] = field(default_factory=list)
    current: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)
    numeric: bool = False
    page: int | None = None
    document_title: str | None = None
    excerpt_language: str | None = None

    def claim_key(self, org_number: str) -> str:
        return "|".join([org_number, self.field, self.key_suffix or "", self.reporting_period or ""])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Rejection:
    field: str
    value: Any
    reason: str
    source_url: str | None
    module: str
    identity_score: float | None = None


@dataclass
class Absence:
    """An explicit, evidenced statement that a field was checked and not established."""

    field: str
    availability: Availability
    modules: list[str]
    note: str
