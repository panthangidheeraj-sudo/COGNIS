"""Public procurement from free sources — an optional enrichment.

Two sources, never presented as complete coverage of Norwegian procurement:

* **TED Search API** (``api.ted.europa.eu``, anonymous): notices published in the EU's Official Journal. Norwegian
  contracting authorities publish their *above-threshold* procurements there (EEA rules); below-threshold notices
  that appear only on Doffin are not in TED.
* **Doffin open data** (DFØ's yearly CSV files, listed on data.norge.no): imported offline with
  ``scripts/import_doffin_open_data.py``. Facts from it are labelled with the dataset's own period — it is a
  periodically published dataset, not a live feed.

Doffin's subscription API is not used.

Identity: a notice is attached to a company only when the company's organisation number appears in the identifier of
the role (winner/supplier or buyer) — checked here, then enforced again by the evidence gate. A notice that names the
company without its number stays an unverified candidate. Every fact keeps its notice id, publication date, source
URL and the exact identifier that matched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core.util import clean_ws, now_iso, truncate
from ..evidence.models import ModuleResult, Observation
from ..identity.employer import exact_legal_name, org_numbers_in
from ..identity.model import CanonicalIdentity
from ..identity.normalization import format_org_number, is_generic_name
from ..storage.db import Database
from .base import ConnectorContext, module_from_fetch, not_run

TED_SOURCE = ("ted", "TED — Tenders Electronic Daily (EU)")
DOFFIN_SOURCE = ("doffin_open", "Doffin open data (DFØ)")
SOURCE_CLASS = "official_procurement_notice"
DOFFIN_DATASET_PAGE = "https://data.norge.no/datasets/a77b0408-85f9-3e12-8a66-8d500b492e9d"
TED_NOTICE_PAGE = "https://ted.europa.eu/en/notice/-/detail/{pub}"
TED_FIELDS = ["publication-number", "publication-date", "notice-type", "notice-title", "buyer-name", "buyer-identifier", "buyer-country",
              "winner-name", "winner-identifier", "classification-cpv", "total-value", "total-value-cur"]
TED_COVERAGE = ("TED holds notices published in the EU's Official Journal — Norwegian above-threshold procurements. Below-threshold notices published only "
                "on Doffin are not included, so this is not complete Norwegian procurement coverage.")
FIELD_FOR_ROLE = {"winner": "procurement_award", "buyer": "procurement_notice_as_buyer"}
LABEL_FOR_ROLE = {"winner": "Public contract awarded", "buyer": "Public procurement notice (as buyer)"}
NOTICE_TYPES = [("can-modif", "Contract modification notice"), ("can", "Contract award notice"), ("veat", "Voluntary ex-ante transparency notice"),
                ("cn", "Contract notice"), ("pin", "Prior information notice"), ("qu-sy", "Qualification system notice"), ("compl", "Contract completion notice")]


def notice_type_label(code: str | None) -> str | None:
    c = (code or "").lower()
    for prefix, label in NOTICE_TYPES:
        if c.startswith(prefix):
            return label
    return code or None


def _values(value: Any) -> list[str]:
    """TED field values come as a string, a list, or a language map ({"eng": [...], "nor": [...]}); English first."""
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        keys = sorted(value, key=lambda k: (k.lower() not in ("eng", "en"), k.lower() not in ("nor", "nob", "no"), k))
        out: list[str] = []
        for k in keys:
            out.extend(_values(value[k]))
        return list(dict.fromkeys(out))
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_values(v))
        return list(dict.fromkeys(out))
    text = clean_ws(str(value))
    return [text] if text else []


def _first(value: Any) -> str | None:
    vals = _values(value)
    return vals[0] if vals else None


def _date(value: Any) -> str | None:
    m = re.search(r"\d{4}-\d{2}-\d{2}", _first(value) or "")
    return m.group(0) if m else None


def _ted_url(notice: dict[str, Any], pub: str) -> str:
    links = notice.get("links") if isinstance(notice.get("links"), dict) else {}
    html = links.get("html") if isinstance(links, dict) else None
    if isinstance(html, dict):
        for key in ("ENG", "eng", "EN", "en", *html.keys()):
            if isinstance(html.get(key), str) and html[key].startswith("https://"):
                return html[key]
    return TED_NOTICE_PAGE.format(pub=pub)


@dataclass
class ProcurementMatch:
    notice_id: str
    role: str  # winner | buyer
    title: str | None
    notice_type: str | None
    published: str | None
    url: str
    matched_identifier: str | None
    buyer_name: str | None = None
    party_names: list[str] = field(default_factory=list)
    cpv: list[str] = field(default_factory=list)
    total_value: str | None = None
    total_value_currency: str | None = None


def ted_query(identity: CanonicalIdentity) -> str:
    org = identity.org_number
    variants = [org, f"NO{org}", f"{org}MVA", f"NO{org}MVA", f'"{format_org_number(org)}"']
    clauses = [f"{role}-identifier={v}" for role in ("winner", "buyer") for v in variants]
    if identity.legal_name and not is_generic_name(identity.legal_name):
        name = identity.legal_name.replace('"', "")
        clauses += [f'winner-name="{name}"', f'buyer-name="{name}"']  # candidates only; publication needs the number
    return " OR ".join(clauses)


def parse_ted_notices(body: Any, identity: CanonicalIdentity) -> tuple[list[ProcurementMatch], list[dict[str, Any]], int | None]:
    """→ (exact matches, unverified name-only candidates, total notice count reported by TED)."""
    if not isinstance(body, dict):
        return [], [], None
    org = identity.org_number
    matches: list[ProcurementMatch] = []
    candidates: list[dict[str, Any]] = []
    for notice in body.get("notices") or []:
        if not isinstance(notice, dict):
            continue
        pub = _first(notice.get("publication-number"))
        if not pub:
            continue
        common = {"notice_id": pub, "title": _first(notice.get("notice-title")), "notice_type": _first(notice.get("notice-type")),
                  "published": _date(notice.get("publication-date")), "url": _ted_url(notice, pub), "buyer_name": _first(notice.get("buyer-name")),
                  "cpv": _values(notice.get("classification-cpv"))[:8], "total_value": _first(notice.get("total-value")),
                  "total_value_currency": _first(notice.get("total-value-cur"))}
        found = False
        for role in ("winner", "buyer"):
            ids = _values(notice.get(f"{role}-identifier"))
            hit = next((i for i in ids if org in org_numbers_in([i])), None)
            if hit:
                found = True
                matches.append(ProcurementMatch(role=role, matched_identifier=hit, party_names=_values(notice.get(f"{role}-name"))[:6], **common))
        if not found:
            named = [r for r in ("winner", "buyer") if any(exact_legal_name(n, identity) for n in _values(notice.get(f"{r}-name")))]
            if named:
                candidates.append({"notice_id": pub, "roles": named, "url": common["url"], "status": "ambiguous",
                                   "reason": "The notice names the company but its identifier does not state this organisation number."})
    total = body.get("totalNoticeCount")
    return matches, candidates, int(total) if isinstance(total, int) else None


def match_observation(m: ProcurementMatch, *, module: str, source: tuple[str, str], retrieved_at: str | None, content_sha256: str | None, org: str,
                      coverage: str, dataset: str | None = None, dataset_period: str | None = None) -> Observation:
    type_label = notice_type_label(m.notice_type)
    who = "; ".join(m.party_names[:3]) or "this organisation"
    span = (f"{'TED' if source[0] == 'ted' else 'Doffin'} notice {m.notice_id}" + (f" ({type_label})" if type_label else "") +
            (f", published {m.published}" if m.published else "") + (f" [dataset {dataset}, period {dataset_period}]" if dataset else "") +
            f": {m.role} {who} — identifier {m.matched_identifier}" + (f"; buyer {m.buyer_name}" if m.role == "winner" and m.buyer_name else "") +
            (f'; "{truncate(m.title, 140)}"' if m.title else ""))
    return Observation(
        field=FIELD_FOR_ROLE[m.role], value=m.title or type_label or f"Notice {m.notice_id}", key_suffix=f"{source[0]}-{m.notice_id}", module=module,
        source_id=source[0], source_name=source[1], source_class=SOURCE_CLASS, source_url=m.url, retrieved_at=retrieved_at, content_sha256=content_sha256,
        claim_span=span, extraction_method="ted_search_api" if source[0] == "ted" else "doffin_open_data", tier="A", label=LABEL_FOR_ROLE[m.role],
        as_of=m.published, effective_from=m.published, identity_score=1.0, identity_signals=["org_number_in_identifier"],
        attributes={"role": m.role, "notice_id": m.notice_id, "notice_type": m.notice_type, "notice_type_label": type_label, "published": m.published,
                    "buyer_name": m.buyer_name, "parties": m.party_names, "cpv": m.cpv, "matched_identifier": m.matched_identifier, "org_number": org,
                    "identity_basis": "org_number_in_identifier", "coverage": coverage, "url": m.url,
                    **({"total_value": m.total_value, "total_value_currency": m.total_value_currency} if m.total_value and m.total_value_currency else {}),
                    **({"dataset": dataset, "dataset_period": dataset_period} if dataset else {})},
    )


@dataclass
class ProcurementResult:
    modules: list[ModuleResult] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)


async def ted_notices(ctx: ConnectorContext, identity: CanonicalIdentity) -> ProcurementResult:
    s = ctx.settings
    out = ProcurementResult()
    if not s.enable_ted:
        out.modules.append(not_run("procurement_ted", source_id=TED_SOURCE[0], source_name=TED_SOURCE[1], source_class=SOURCE_CLASS, state="not_applicable",
                                   note="TED lookup disabled by configuration."))
        return out
    body = {"query": ted_query(identity), "fields": TED_FIELDS, "page": 1, "limit": s.ted_max_notices_per_company, "scope": "ALL", "paginationMode": "PAGE_NUMBER"}
    res = await ctx.fetch(f"{s.ted_api_base.rstrip('/')}/notices/search", connector="ted", method="POST", json_body=body, accept="application/json",
                          headers={"Content-Type": "application/json"}, expect="json", optional=True, cache_ttl=s.cache_ttl_search_seconds, interval_key="ted")
    data = res.json() if res.ok else None
    matches, cands, total = parse_ted_notices(data, identity) if res.ok else ([], [], None)
    mod = module_from_fetch("procurement_ted", source_id=TED_SOURCE[0], source_name=TED_SOURCE[1], source_class=SOURCE_CLASS, result=res,
                            value={"matches": len(matches), "unverified": len(cands), "total_reported": total})
    if res.ok:
        mod.note = (f"{len(matches)} notice(s) state this organisation number" + (f"; {len(cands)} name-only notice(s) not used" if cands else "") +
                    (f"; first {s.ted_max_notices_per_company} of {total} examined" if total and total > s.ted_max_notices_per_company else "") + ". " + TED_COVERAGE)
    elif res.status == 400:
        mod.note = "TED rejected the search request (HTTP 400) — its query syntax or field names may have changed."
    out.modules.append(mod)
    for m in matches:
        out.observations.append(match_observation(m, module="procurement_ted", source=TED_SOURCE, retrieved_at=res.retrieved_at, content_sha256=res.content_sha256,
                                                  org=identity.org_number, coverage="TED (EU-published notices)"))
    out.candidates += cands
    return out


def doffin_open_data(db: Database | None, identity: CanonicalIdentity, *, enabled: bool) -> ProcurementResult:
    out = ProcurementResult()
    args = {"source_id": DOFFIN_SOURCE[0], "source_name": DOFFIN_SOURCE[1], "source_class": SOURCE_CLASS}
    if not enabled:
        out.modules.append(not_run("procurement_doffin", **args, state="not_applicable", note="Doffin open data disabled by configuration."))
        return out
    if db is None or not db.one("SELECT 1 FROM procurement_notices LIMIT 1"):
        out.modules.append(not_run("procurement_doffin", **args, state="not_applicable",
                                   note="DFØ's open Doffin dataset has not been imported (scripts/import_doffin_open_data.py); Doffin's subscription API is not used."))
        return out
    periods = [r["dataset_period"] for r in db.all("SELECT DISTINCT dataset_period FROM procurement_notices WHERE dataset_period IS NOT NULL ORDER BY dataset_period")]
    rows = db.all("SELECT n.*, p.role, p.name AS party_name, p.org_number FROM procurement_parties p JOIN procurement_notices n ON n.notice_key = p.notice_key "
                  "WHERE p.org_number = ? ORDER BY n.published_at DESC LIMIT 200", (identity.org_number,))
    coverage = "Doffin open dataset (DFØ), periods " + ", ".join(periods) if periods else "Doffin open dataset (DFØ)"
    for r in rows:
        m = ProcurementMatch(notice_id=r["notice_id"], role="winner" if r["role"] == "winner" else "buyer", title=r["title"], notice_type=r["notice_type"],
                             published=r["published_at"], url=r["url"] or DOFFIN_DATASET_PAGE, matched_identifier=r["org_number"], buyer_name=r["buyer_name"],
                             party_names=[r["party_name"]] if r["party_name"] else [])
        out.observations.append(match_observation(m, module="procurement_doffin", source=DOFFIN_SOURCE, retrieved_at=r["imported_at"], content_sha256=r["row_sha256"],
                                                  org=identity.org_number, coverage=coverage, dataset=r["dataset"], dataset_period=r["dataset_period"]))
    mod = not_run("procurement_doffin", **args, state="available", url=DOFFIN_DATASET_PAGE,
                  note=f"{len(rows)} notice(s) in the imported Doffin dataset list this organisation number ({coverage}). Historical dataset, not a live feed.")
    mod.retrieved_at = now_iso()
    mod.value = {"matches": len(rows), "periods": periods}
    out.modules.append(mod)
    return out

