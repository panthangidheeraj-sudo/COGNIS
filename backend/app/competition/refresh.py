"""Refresh replay: evaluator-owned old/new source bytes → production connectors → change events.

The manifest format is the starter kit's ``tests/fixtures/refresh-snapshots.json``:
``modules``, ``profiles``, ``snapshots.{old,new}.{retrieved_at, effective_at, responses{url: {status, body}}}``
and ``expected_changes``. Responses are served through an in-process transport,
so the same normalisers and change detector as production runs are exercised.
"""
from __future__ import annotations

import copy
import json
from typing import Any

import httpx

from ..config import get_settings
from ..connectors import brreg, website
from ..connectors.base import ConnectorContext
from ..identity.model import CanonicalIdentity
from ..net.http import HttpClient
from ..runtime.budgets import unlimited_budget
from .changes import compat_profile, diff_datasets


class SnapshotTransport(httpx.AsyncBaseTransport):
    def __init__(self, snapshot: dict[str, Any]):
        self.responses = snapshot.get("responses") or {}
        self.requests: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        item = self.responses.get(url)
        if item is None:
            return httpx.Response(404, json={"status": 404})
        body = item.get("body")
        status = int(item.get("status") or 200)
        if isinstance(body, (dict, list)):
            return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json"})
        return httpx.Response(status, text=str(body or ""), headers={"content-type": item.get("content_type") or "text/html"})


async def materialize(base_profiles: list[dict[str, Any]], snapshot: dict[str, Any], modules: set[str]) -> tuple[list[dict[str, Any]], int]:
    transport = SnapshotTransport(snapshot)
    rows: list[dict[str, Any]] = []
    async with HttpClient(transport=transport) as http:
        for base in base_profiles:
            org = base["organisation_number"]
            ctx = ConnectorContext(org_number=org, http=http, budget=unlimited_budget(), run_id="refresh-replay", settings=get_settings(), fresh=True)
            mods: dict[str, Any] = {}
            identity: CanonicalIdentity | None = None
            if "registry_live" in modules or "registry" in modules:
                mod, identity = await brreg.fetch_entity(ctx)
                mods["registry_live"] = mod
            if "financials" in modules:
                mods["financials"] = await brreg.fetch_financials(ctx, identity)
            if "financial_history" in modules:
                mods["financial_history"] = await brreg.fetch_financial_history(ctx, identity)
            if "roles" in modules:
                mods["roles"] = await brreg.fetch_roles(ctx)
            if "locations" in modules:
                mods["locations"] = await brreg.fetch_locations(ctx)
            if "group" in modules:
                mods["group"] = await brreg.fetch_group(ctx, identity)
            if "website" in modules and identity is not None and identity.website:
                crawl = await website.crawl_site(ctx, identity.website, identity, origin="registry", max_pages=3)
                mods["website"] = crawl.module()
            for mod in mods.values():
                # Evaluator-owned bytes carry their own capture times.
                if snapshot.get("retrieved_at"):
                    mod.retrieved_at = snapshot["retrieved_at"]
                mod.effective_at = snapshot.get("effective_at") or mod.retrieved_at
            record = {"organisation_number": org, "identity": identity.to_dict() if identity else None,
                      "modules": {name: m.snapshot_meta() for name, m in mods.items()}, "claims": [], "jobs": {}}
            profile = compat_profile(record)
            merged = copy.deepcopy(base)
            for key, value in profile.items():
                if key == "evidence":
                    merged.setdefault("evidence", {}).update(value)
                elif value is not None or key not in merged:
                    merged[key] = value
            rows.append(merged)
    return rows, len(transport.requests)


async def replay(manifest: dict[str, Any]) -> dict[str, Any]:
    modules = set(manifest.get("modules") or ["registry_live", "financials"])
    base = manifest["profiles"]
    previous, old_requests = await materialize(base, manifest["snapshots"]["old"], modules)
    current, new_requests = await materialize(base, manifest["snapshots"]["new"], modules)
    changes = diff_datasets(previous, current)
    observed = {(c["organisation_number"], c["field"]) for c in changes}
    expected = {(c["organisation_number"], c["field"]) for c in manifest.get("expected_changes", [])}
    tp = len(expected & observed)
    fp = len(observed - expected)
    fn = len(expected - observed)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    evidence_complete = all(c.get("source_url") and c.get("retrieved_at") and c.get("effective_at") and c.get("old_content_sha256") and c.get("new_content_sha256")
                            for c in changes)
    idempotent = diff_datasets(current, current) == [] and diff_datasets(previous, previous) == []
    return {
        "corpus": manifest.get("corpus", "evaluator-owned snapshot replay"),
        "profiles": len(base),
        "modules": sorted(modules),
        "old_requests": old_requests,
        "new_requests": new_requests,
        "expected_changes": len(expected),
        "observed_changes": len(observed),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "evidence_complete": evidence_complete,
        "idempotent_rerun": idempotent,
        "qualification_passed": precision >= 0.95 and recall >= 0.95 and evidence_complete and idempotent,
        "events": changes,
    }
