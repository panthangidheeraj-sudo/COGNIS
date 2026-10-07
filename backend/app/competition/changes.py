"""Change detection between two profiles of the same organisation number.

Profiles use the starter kit's shape (top-level registry fields + per-module
``evidence`` records) so ``--previous-profiles`` files from either system work.
Values are compared in canonical form (whitespace, URL tracking parameters,
``www.``/trailing-slash variants, link ordering), so only material changes are
reported; a module that failed or was not checked in either run is never
evidence of change. Every event carries the source URL, retrieval time,
effective time and both content hashes.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from ..core.util import now_iso, stable_id

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "mc_cid", "mc_eid", "_ga", "ref", "ref_src", "igshid"}

TRACKED_FIELDS: dict[str, tuple[str, ...]] = {
    "registry.name": ("name",),
    "registry.legal_form": ("legal_form",),
    "registry.employees": ("employees",),
    "registry.municipality": ("municipality",),
    "registry.website": ("website",),
    "registry.latest_submitted_accounts": ("latest_submitted_accounts",),
    "registry.status": ("status",),
    "registry.business_address": ("business_address",),
    "financials.records": ("evidence", "financials", "value", "records"),
    "financial_history.years": ("evidence", "financial_history", "value", "years"),
    "roles.roles": ("evidence", "roles", "value", "roles"),
    "locations.locations": ("evidence", "locations", "value", "locations"),
    "website.title": ("evidence", "website", "value", "title"),
    "website.description": ("evidence", "website", "value", "description"),
    "website.social_links": ("evidence", "website", "value", "social_links"),
    "external_footprint.active_job_count": ("external_metrics", "active_job_count"),
    "external_footprint.public_item_count": ("external_metrics", "public_item_count"),
}

# field → (frontend category, label, material)
FIELD_META: dict[str, tuple[str, str, bool]] = {
    "registry.name": ("status", "Legal name", True),
    "registry.legal_form": ("status", "Legal form", True),
    "registry.employees": ("employees", "Registered employees", True),
    "registry.municipality": ("address", "Municipality", True),
    "registry.website": ("website", "Registered website", False),
    "registry.latest_submitted_accounts": ("filing", "Latest submitted annual accounts", True),
    "registry.status": ("status", "Registration status", True),
    "registry.business_address": ("address", "Business address", True),
    "financials.records": ("financial", "Annual accounts", True),
    "financial_history.years": ("filing", "Filed annual reports", True),
    "roles.roles": ("leadership", "Registered roles", True),
    "locations.locations": ("location", "Registered establishments", True),
    "website.title": ("website", "Website title", False),
    "website.description": ("website", "Website description", False),
    "website.social_links": ("website", "Social profiles", False),
    "external_footprint.active_job_count": ("hiring", "Open positions", True),
    "external_footprint.public_item_count": ("event", "Published news items", False),
}

STARTER_STATUS = {"available": "available", "not_available": "not_found", "ambiguous": "not_found", "blocked": "blocked", "failed": "source_error",
                  "not_applicable": "not_applicable"}


def _canonical_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value.strip())
    if not parsed.scheme and not parsed.netloc:
        return re.sub(r"\s+", " ", value.strip())
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query) if k.lower() not in _TRACKING_PARAMS]
    return urllib.parse.urlunparse(("https", netloc, path, "", urllib.parse.urlencode(sorted(kept)), ""))


def canonicalize(field: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if field.endswith("website") or field.endswith("social_links") or re.match(r"^\s*(https?://|www\.)", stripped, re.I):
            return _canonical_url(stripped if "://" in stripped else "https://" + stripped)
        return re.sub(r"\s+", " ", stripped)
    if isinstance(value, dict):
        return {k: canonicalize(f"{field}.{k}", value[k]) for k in sorted(value)}
    if isinstance(value, list):
        items = [canonicalize(field, v) for v in value]
        if field.endswith(("social_links", "roles", "locations", "years")):
            return sorted(items, key=lambda i: json.dumps(i, sort_keys=True, ensure_ascii=False))
        return items
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _read(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _module_record(profile: dict[str, Any], field: str) -> dict[str, Any]:
    module = field.split(".", 1)[0]
    records = profile.get("evidence") or {}
    if module == "registry":
        return records.get("registry_live") or records.get("registry") or {}
    if module == "external_footprint":
        return records.get("jobs") or {} if field.endswith("job_count") else records.get("website") or {}
    return records.get(module) or {}


def _checked(record: dict[str, Any], field: str) -> bool:
    if field.startswith("registry."):
        return True  # top-level registry fields always come from a register (live or bulk)
    return record.get("status") in ("available", "not_found")


def compat_profile(record: dict[str, Any]) -> dict[str, Any]:
    """Starter-compatible profile from a research record."""
    modules = record.get("modules") or {}
    identity = record.get("identity") or {}
    live = modules.get("registry_live") or {}
    bulk = modules.get("registry") or {}
    live_value = live.get("value") if live.get("state") == "available" else None
    bulk_value = bulk.get("value") if bulk.get("state") == "available" else None
    source = live_value or bulk_value or {}

    def pick(key: str, fallback: Any = None) -> Any:
        if isinstance(source, dict) and key in source:
            return source.get(key)
        return fallback

    addr = identity.get("business_address") or {}
    evidence: dict[str, Any] = {}
    for name, mod in modules.items():
        evidence[name] = {
            "status": STARTER_STATUS.get(mod.get("state"), "source_error"), "state": mod.get("state"), "source_class": mod.get("source_class"),
            "source_url": mod.get("final_url") or mod.get("url"), "retrieved_at": mod.get("retrieved_at"), "effective_at": mod.get("effective_at") or mod.get("retrieved_at"),
            "content_sha256": mod.get("content_sha256"), "value": mod.get("value"), "note": mod.get("note"),
        }
    jobs = record.get("jobs") or {}
    news = [c for c in record.get("claims") or [] if c.get("field") == "news_item"]
    metrics: dict[str, Any] = {}
    if jobs.get("checked") or jobs.get("items"):
        metrics["active_job_count"] = sum(1 for j in jobs.get("items") or [] if j.get("state") == "current")
    if news:
        metrics["public_item_count"] = len(news)
    return {
        "organisation_number": record["organisation_number"],
        "name": pick("name", identity.get("legal_name")),
        "legal_form": pick("legal_form", identity.get("legal_form")),
        "employees": pick("employees", identity.get("employees")),
        "municipality": identity.get("municipality") or pick("municipality"),
        "municipality_number": identity.get("municipality_number"),
        "industry_code": identity.get("industry_code"),
        "industry_label": identity.get("industry_label"),
        "website": pick("website", identity.get("website_raw") or identity.get("website")),
        "latest_submitted_accounts": pick("latest_submitted_accounts", identity.get("latest_accounts_year")),
        "status": identity.get("status"),
        "business_address": " ".join([*(addr.get("adresse") or []), addr.get("postnummer") or "", addr.get("poststed") or ""]).strip() or None,
        "bankrupt": identity.get("status") == "bankruptcy",
        "liquidating": identity.get("status") == "under_liquidation",
        "evidence": evidence,
        "external_metrics": metrics,
        "run_id": record.get("run_id"),
        "researched_at": record.get("completed_at"),
    }


def _numeric_direction(old: Any, new: Any) -> str | None:
    try:
        a, b = float(old), float(new)
    except (TypeError, ValueError):
        return None
    return "up" if b > a else "down" if b < a else None


def _display(field: str, value: Any) -> str | None:
    if value is None:
        return None
    if field == "roles.roles" and isinstance(value, list):
        return ", ".join(f"{r.get('role')}: {r.get('name')}" for r in value if isinstance(r, dict) and not r.get("inactive"))[:300]
    if field == "financials.records" and isinstance(value, list) and value:
        r = value[0]
        period = (r.get("period") or {}).get("tilDato") if isinstance(r.get("period"), dict) else r.get("period")
        currency = f" {r['currency']}" if r.get("currency") else ""  # the amounts are in the filing's own currency; say which
        return f"{period}: revenue {r.get('revenue')}{currency}, result {r.get('annual_result')}{currency}"
    if field == "locations.locations" and isinstance(value, list):
        return f"{len(value)} establishment(s)"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:300]
    return str(value)


def _headline(field: str, old: Any, new: Any, kind: str) -> str:
    label = FIELD_META.get(field, ("event", field, True))[1]
    if field == "roles.roles":
        old_ceo = next((r.get("name") for r in old or [] if isinstance(r, dict) and r.get("role_code") == "DAGL" and not r.get("inactive")), None)
        new_ceo = next((r.get("name") for r in new or [] if isinstance(r, dict) and r.get("role_code") == "DAGL" and not r.get("inactive")), None)
        if old_ceo != new_ceo and new_ceo:
            return "CEO changed"
        return "Board or roles changed"
    if field == "financials.records":
        old_p = json.dumps((old or [{}])[0].get("period") if isinstance(old, list) and old else None, sort_keys=True)
        new_p = json.dumps((new or [{}])[0].get("period") if isinstance(new, list) and new else None, sort_keys=True)
        return "New annual accounts" if old_p != new_p else "Annual accounts updated"
    if field in ("registry.employees", "external_footprint.active_job_count") and old is not None and new is not None:
        return f"{label} {old} → {new}"
    if kind == "added":
        return f"{label} added"
    if kind == "removed":
        return f"{label} removed"
    return f"{label} changed"


def diff_profile(previous: dict[str, Any], current: dict[str, Any], *, detected_at: str | None = None) -> list[dict[str, Any]]:
    old_org = previous.get("organisation_number")
    new_org = current.get("organisation_number")
    if not old_org or old_org != new_org:
        raise ValueError("Refresh comparison requires the same exact organisation number")
    changes = []
    detected = detected_at or now_iso()
    for field, path in TRACKED_FIELDS.items():
        old_record = _module_record(previous, field)
        new_record = _module_record(current, field)
        if field.startswith("registry."):
            if path[0] not in previous or path[0] not in current:
                continue  # a profile format that does not carry this field is not evidence of change
        elif not (_checked(old_record, field) and _checked(new_record, field)):
            continue  # a source that failed or was not checked is not evidence of change
        old_value, new_value = _read(previous, path), _read(current, path)
        if field.startswith("external_footprint") and (old_value is None or new_value is None):
            continue
        if canonicalize(field, old_value) == canonicalize(field, new_value):
            continue
        kind = "added" if old_value in (None, [], "") else "removed" if new_value in (None, [], "") else "modified"
        category, label, material = FIELD_META.get(field, ("event", field, True))
        changes.append({
            "id": "chg-" + stable_id(new_org, field, json.dumps(canonicalize(field, old_value), sort_keys=True, default=str),
                                     json.dumps(canonicalize(field, new_value), sort_keys=True, default=str), length=14),
            "organisation_number": new_org,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "source_url": new_record.get("source_url"),
            "retrieved_at": new_record.get("retrieved_at"),
            "effective_at": new_record.get("effective_at") or new_record.get("retrieved_at"),
            "source_class": new_record.get("source_class"),
            "old_content_sha256": old_record.get("content_sha256"),
            "new_content_sha256": new_record.get("content_sha256"),
            "status": new_record.get("status"),
            "detected_at": detected,
            "kind": kind,
            "category": category,
            "label": label,
            "material": material,
            "headline": _headline(field, old_value, new_value, kind),
            "direction": _numeric_direction(old_value, new_value) if not isinstance(new_value, (list, dict)) else None,
            "old_display": _display(field, old_value),
            "new_display": _display(field, new_value),
        })
    return changes


def diff_datasets(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_by_org = {row["organisation_number"]: row for row in previous}
    new_by_org = {row["organisation_number"]: row for row in current}
    if set(old_by_org) != set(new_by_org):
        raise ValueError("Refresh datasets must have identical organisation-number membership")
    return [change for org in sorted(old_by_org) for change in diff_profile(old_by_org[org], new_by_org[org])]
