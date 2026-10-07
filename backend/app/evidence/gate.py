"""Deterministic publication gate, conflict resolver and absence claims.

Python — not the LLM — decides what is published:

* every published value needs a source URL, a retrieval time, an exact
  claim span and an extraction method;
* search results and discovery-tier observations are never evidence;
* website-derived observations need a verified exact-entity identity score;
* numbers must be real numbers from the source (missing is never zero) and
  financial numbers must carry their reporting period and the currency their
  own evidence states (a currency is never assumed);
* LLM-extracted text is only accepted when its quote was found verbatim.

Observations for the same claim key are merged: identical values corroborate,
different values are resolved by source authority then recency, and the
disagreement is kept (never silently dropped).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.util import clean_ws, fold
from ..security.urls import canonical_url
from .models import AVAILABILITY_STATES, Absence, Availability, ModuleResult, Observation, Rejection

# Lower rank = more authoritative.
SOURCE_RANK: dict[str, int] = {
    "official_registry_live": 0,
    "official_annual_accounts": 0,
    "official_roles": 0,
    "official_subunits": 0,
    "official_group_structure": 0,
    "official_annual_account_copies": 0,
    "official_registry_bulk": 1,
    "official_classification": 1,
    "official_other": 1,
    "company_owned": 2,
    "company_owned_email_domain": 3,
    "company_owned_discovered": 3,
    "company_linked_social_profile": 3,
    "company_linked_job_board": 3,
    "licensed_secondary": 4,
}
OFFICIAL_CLASSES = {k for k, v in SOURCE_RANK.items() if v <= 1}
WEBSITE_CLASSES = {"company_owned", "company_owned_email_domain", "company_owned_discovered", "company_linked_social_profile", "company_linked_job_board"}
NEVER_EVIDENCE = {"search_result", "search_snippet", "web_search", "llm_generated"}

CONFIDENCE: dict[str, float] = {
    "official_registry_live": 0.99, "official_registry_bulk": 0.98, "official_annual_accounts": 0.98, "official_roles": 0.97,
    "official_subunits": 0.97, "official_group_structure": 0.97, "official_annual_account_copies": 0.97, "official_classification": 0.95,
    "company_owned": 0.9, "company_owned_email_domain": 0.88, "company_owned_discovered": 0.85, "company_linked_social_profile": 0.88,
    "company_linked_job_board": 0.85, "licensed_secondary": 0.8,
}
MIN_WEBSITE_IDENTITY = 0.6

NUMERIC_FIELDS = {
    "registered_employees", "reported_employees", "share_capital", "open_positions_count", "registered_establishment_count",
}
FINANCIAL_FIELDS = {
    "revenue", "operating_expenses", "payroll_expenses", "operating_result", "net_financial_items", "profit_before_tax", "tax_expense",
    "annual_result", "total_assets", "fixed_assets", "current_assets", "cash_and_bank", "equity", "debt", "short_term_debt", "long_term_debt",
}


@dataclass
class Claim:
    field: str
    value: Any
    availability: Availability
    confidence: float | None
    label: str | None = None
    key_suffix: str | None = None
    reporting_period: str | None = None
    period_label: str | None = None
    unit: str | None = None
    currency: str | None = None
    as_of: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    current: bool = True
    source_class: str | None = None
    observations: list[Observation] = field(default_factory=list)
    conflict: dict[str, Any] | None = None
    note: str | None = None
    modules: list[str] = field(default_factory=list)  # modules consulted (absence claims)
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def primary(self) -> Observation | None:
        return self.observations[0] if self.observations else None

    def key(self, org: str) -> str:
        return "|".join([org, self.field, self.key_suffix or "", self.reporting_period or ""])


def canonical_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = clean_ws(value)
        if re.match(r"^https?://", text, re.I):
            return canonical_url(text)
        return fold(text)
    if isinstance(value, (list, tuple)):
        return tuple(canonical_value(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, canonical_value(v)) for k, v in value.items()))
    return value


def currency_problem(obs: Observation) -> str | None:
    """A monetary amount is only publishable with the currency its own evidence states.

    * a stated currency must be a three-letter code, must match ``unit`` when one is given, and must literally appear in the
      evidence span (so the label shown to a user can never contradict the excerpt shown next to it);
    * an amount with no stated currency is only accepted from the structured register, which marks it ``not_stated`` —
      a currency is never guessed, and a website/LLM-extracted amount without a currency is rejected.
    """
    currency = obs.currency
    if currency is None:
        if obs.unit:
            return "monetary amount has a unit but no currency"
        if obs.extraction_method != "structured_api":
            return "monetary amount without a stated currency"
        return None
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return "currency is not a three-letter code"
    if obs.unit and obs.unit != currency:
        return f"unit ({obs.unit}) and currency ({currency}) disagree"
    if not re.search(rf"(?<![A-Za-z]){currency}(?![A-Za-z])", obs.claim_span or ""):
        return f"stated currency {currency} does not appear in the evidence span"
    return None


def check(obs: Observation) -> str | None:
    """Return a rejection reason, or None when the observation may be published."""
    if obs.source_class in NEVER_EVIDENCE or obs.tier == "C":
        return "search results and discovery hints are candidates, not evidence"
    if not obs.source_url:
        return "no source URL"
    if not obs.retrieved_at:
        return "no retrieval time"
    if not clean_ws(obs.claim_span):
        return "no evidence span"
    if not obs.extraction_method:
        return "no extraction method"
    value = obs.value
    if value is None or (isinstance(value, str) and not clean_ws(value)) or value in ([], {}):
        return "empty value"
    if obs.source_class in WEBSITE_CLASSES and obs.identity_score < MIN_WEBSITE_IDENTITY:
        return f"website identity not established (score {obs.identity_score:.2f})"
    if obs.field in FINANCIAL_FIELDS or obs.field.startswith("consolidated_") or obs.numeric or obs.field in NUMERIC_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            return "numeric field without a real number"
    if (obs.field in FINANCIAL_FIELDS or obs.field.startswith("consolidated_")) and not obs.reporting_period:
        return "financial value without a reporting period"
    if obs.field in FINANCIAL_FIELDS or obs.field.startswith("consolidated_") or obs.field == "share_capital":
        problem = currency_problem(obs)
        if problem:
            return problem
    if obs.extraction_method.startswith("llm") and not obs.attributes.get("quote_verified"):
        return "LLM extraction whose quote was not found verbatim on the page"
    if isinstance(value, str) and obs.field.endswith(("website", "_url", "_page")) and not re.match(r"^https?://", value):
        if obs.field != "registered_website":
            return "URL value is not http(s)"
    return None


def _rank(obs: Observation) -> tuple[int, str]:
    # Authority first; within a class the most recent retrieval wins (reversed string sort via negation trick below).
    return SOURCE_RANK.get(obs.source_class, 5), obs.retrieved_at or ""


def _confidence(claim: Claim) -> float:
    base = CONFIDENCE.get(claim.source_class or "", 0.75)
    distinct_sources = {o.source_id for o in claim.observations}
    if len(distinct_sources) >= 2:
        base = min(0.99, base + 0.02)
    if claim.conflict:
        base = max(0.5, base - 0.1)
    return round(base, 2)


def publish(observations: list[Observation], org: str) -> tuple[list[Claim], list[Rejection]]:
    rejections: list[Rejection] = []
    accepted: list[Observation] = []
    seen: set[tuple] = set()
    for obs in observations:
        reason = check(obs)
        if reason:
            rejections.append(Rejection(field=obs.field, value=obs.value, reason=reason, source_url=obs.source_url, module=obs.module, identity_score=obs.identity_score))
            continue
        dedupe = (obs.claim_key(org), canonical_value(obs.value), obs.currency, canonical_url(obs.source_url or ""), obs.source_id)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        accepted.append(obs)

    groups: dict[str, list[Observation]] = {}
    for obs in accepted:
        groups.setdefault(obs.claim_key(org), []).append(obs)

    claims: list[Claim] = []
    for _key, group in groups.items():
        by_value: dict[Any, list[Observation]] = {}
        for obs in group:
            # 100 NOK and 100 USD are different statements: the currency is part of what makes two observations "the same value".
            by_value.setdefault((canonical_value(obs.value), obs.currency), []).append(obs)
        ranked_values = sorted(by_value.items(), key=lambda kv: (min(SOURCE_RANK.get(o.source_class, 5) for o in kv[1]),
                                                                  -max(_ts(o.retrieved_at) for o in kv[1]), -len(kv[1])))
        winner_obs = sorted(ranked_values[0][1], key=lambda o: (SOURCE_RANK.get(o.source_class, 5), -_ts(o.retrieved_at)))
        top = winner_obs[0]
        conflict = None
        if len(ranked_values) > 1:
            candidates = []
            for _cv, items in ranked_values:
                best = sorted(items, key=lambda o: (SOURCE_RANK.get(o.source_class, 5), -_ts(o.retrieved_at)))[0]
                candidates.append({"value": best.value, "currency": best.currency, "source_class": best.source_class, "source_id": best.source_id,
                                   "source_url": best.source_url, "retrieved_at": best.retrieved_at, "observations": items})
            conflict = {
                "reason": _conflict_reason(candidates),
                "resolution": top.source_class,
                "candidates": candidates,
            }
        supporting = winner_obs + ([o for _cv, items in ranked_values[1:] for o in items] if conflict else [])
        claim = Claim(
            field=top.field, value=top.value, availability="available", confidence=None, label=top.label, key_suffix=top.key_suffix,
            reporting_period=top.reporting_period, period_label=top.period_label, unit=top.unit, currency=top.currency, as_of=top.as_of,
            effective_from=top.effective_from, effective_to=top.effective_to, current=top.current, source_class=top.source_class,
            observations=supporting, conflict=conflict, attributes=dict(top.attributes),
        )
        claim.confidence = _confidence(claim)
        claims.append(claim)
    claims.sort(key=lambda c: (FIELD_ORDER.get(c.field, 500), c.field, c.reporting_period or "", c.key_suffix or ""))
    return claims, rejections


def _ts(value: str | None) -> float:
    from ..core.util import parse_iso

    dt = parse_iso(value) if value else None
    return dt.timestamp() if dt else 0.0


def _conflict_reason(candidates: list[dict[str, Any]]) -> str:
    classes = [c["source_class"] for c in candidates]
    if "official_registry_live" in classes and "official_registry_bulk" in classes:
        return "The live register differs from the bulk snapshot; the register may have been updated after the snapshot was taken."
    if any(c in OFFICIAL_CLASSES for c in classes) and any(c in WEBSITE_CLASSES for c in classes):
        return "The company's own website states a different value than the official register; the register is used."
    return "Sources state different values; the more authoritative and more recent source is used."


# ------------------------------------------------------------------ absences --
# field → (modules that would establish it, explanation when checked but absent)
CORE_FIELDS: dict[str, tuple[tuple[str, ...], str]] = {
    "legal_name": (("registry_live", "registry"), "No register record was returned."),
    "registration_status": (("registry_live", "registry"), "No register record was returned."),
    "legal_form": (("registry_live", "registry"), "The register record has no legal form."),
    "industry_code": (("registry_live", "registry"), "The register lists no industry code."),
    "municipality": (("registry_live", "registry"), "The register lists no business-address municipality."),
    "business_address": (("registry_live", "registry"), "The register lists no business address."),
    "founded_date": (("registry_live",), "The register lists no founding date."),
    "registered_employees": (("registry_live", "registry"), "The register reports no employee count (missing is not zero)."),
    "registered_website": (("registry_live", "registry"), "The register lists no website."),
    "ceo": (("roles",), "The roles register lists no general manager (daglig leder)."),
    "board_chair": (("roles",), "The roles register lists no chair of the board."),
    "auditor": (("roles",), "The roles register lists no auditor."),
    "registered_establishment_count": (("locations",), "The establishment register could not be read."),
    "parent_company": (("group",), "The group register lists no parent company."),
    "revenue": (("financials",), "No filed annual accounts state revenue."),
    "operating_result": (("financials",), "No filed annual accounts state an operating result."),
    "profit_before_tax": (("financials",), "No filed annual accounts state profit before tax."),
    "annual_result": (("financials",), "No filed annual accounts state an annual result."),
    "total_assets": (("financials",), "No filed annual accounts state total assets."),
    "equity": (("financials",), "No filed annual accounts state equity."),
    "debt": (("financials",), "No filed annual accounts state total debt."),
    "annual_accounts_filed": (("financial_history",), "No filed annual-account copies are listed."),
    "official_website": (("website",), "No website could be verified as belonging to this exact organisation."),
    "business_description": (("website",), "No company-stated description was found on a verified website."),
    "open_positions_count": (("jobs", "website"), "No current openings could be established from company-owned careers sources."),
    "social_profile_linkedin": (("website",), "The verified website links no company LinkedIn page."),
}

FIELD_ORDER = {name: i for i, name in enumerate([
    "legal_name", "legal_form", "registration_status", "organisation_number", "industry_code", "industry_label", "secondary_industry", "founded_date",
    "registration_date", "business_register_date", "business_address", "postal_address", "municipality", "county", "registered_employees",
    "registered_website", "registered_email", "registered_phone", "vat_registered", "in_business_register", "share_capital", "statutory_purpose",
    "registered_activity", "institutional_sector", "former_name", "part_of_group", "parent_unit", "parent_company", "ultimate_parent_company", "subsidiary",
    "ceo", "board_chair", "deputy_chair", "board_member", "deputy_board_member", "auditor", "accountant", "contact_person", "proprietor",
    "registered_establishment_count", "registered_establishment", "latest_filed_accounts_year", "annual_accounts_filed",
    *sorted(FINANCIAL_FIELDS), "official_website", "website_title", "website_description", "business_description", "contact_email", "contact_phone",
    "social_profile_linkedin", "social_profile_facebook", "social_profile_instagram", "social_profile_x", "social_profile_youtube",
    "open_positions_count", "job_posting", "news_item", "summary",
])}

_STATE_PRIORITY = {"blocked": 0, "failed": 1, "ambiguous": 2, "not_applicable": 3, "not_available": 4}


def absences(claims: list[Claim], modules: dict[str, ModuleResult], *, legal_form: str | None = None) -> list[Absence]:
    present = {c.field for c in claims}
    out: list[Absence] = []
    for fld, (mods, explanation) in CORE_FIELDS.items():
        if fld in present:
            continue
        consulted = [modules[m] for m in mods if m in modules]
        if not consulted:
            continue
        if any(m.state == "available" for m in consulted):
            # The source was checked and answered, but did not state this field.
            state: Availability = "not_available"
            note = explanation
            if fld == "registered_establishment_count":
                continue  # an available subunits module always yields a count
        else:
            worst = sorted(consulted, key=lambda m: _STATE_PRIORITY.get(m.state, 9))[0]
            state = worst.state if worst.state in AVAILABILITY_STATES else "failed"
            note = worst.note or explanation
            if state == "available":
                state = "not_available"
        if fld in {"revenue", "operating_result", "profit_before_tax", "annual_result", "total_assets", "equity", "debt", "annual_accounts_filed"} and legal_form == "ENK" and state == "not_available":
            state, note = "not_applicable", "Sole proprietorships (ENK) generally do not file annual accounts with Regnskapsregisteret."
        out.append(Absence(field=fld, availability=state, modules=[m.module for m in consulted], note=note))
    return out
