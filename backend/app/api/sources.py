"""Frontend ``Source`` objects and evidence mapping (API_CONTRACT evidence model)."""
from __future__ import annotations

from typing import Any

from ..security.urls import host_of, registrable_domain

STATIC_SOURCES: dict[str, dict[str, Any]] = {
    "brreg": {"id": "brreg", "name": "Brønnøysundregistrene", "originalTitle": "Enhetsregisteret", "kind": "registry", "tier": "primary", "official": True,
              "url": "https://www.brreg.no/", "domain": "brreg.no"},
    "roles": {"id": "roles", "name": "Brønnøysundregistrene — roles", "originalTitle": "Enhetsregisteret — roller", "kind": "people", "tier": "primary", "official": True,
              "url": "https://www.brreg.no/", "domain": "brreg.no"},
    "subunits": {"id": "subunits", "name": "Brønnøysundregistrene — sub-units", "originalTitle": "Enhetsregisteret — underenheter", "kind": "registry", "tier": "primary",
                 "official": True, "url": "https://www.brreg.no/", "domain": "brreg.no"},
    "group": {"id": "group", "name": "Brønnøysundregistrene — group structure", "originalTitle": "Konsernstruktur", "kind": "registry", "tier": "primary", "official": True,
              "url": "https://www.brreg.no/", "domain": "brreg.no"},
    "accounts": {"id": "accounts", "name": "Regnskapsregisteret", "originalTitle": "Regnskapsregisteret — årsregnskap", "kind": "financial", "tier": "primary", "official": True,
                 "url": "https://www.brreg.no/", "domain": "brreg.no"},
    "account_copies": {"id": "account_copies", "name": "Regnskapsregisteret — filed annual reports", "originalTitle": "Årsregnskap (kopi)", "kind": "financial",
                       "tier": "primary", "official": True, "url": "https://www.brreg.no/", "domain": "brreg.no"},
    "geonorge": {"id": "geonorge", "name": "Kartverket — Geonorge", "originalTitle": "Adresser / kommuneinfo", "kind": "registry", "tier": "primary", "official": True,
                 "url": "https://www.geonorge.no/", "domain": "geonorge.no"},
    "websearch": {"id": "websearch", "name": "Web search", "kind": "web", "tier": "discovery", "official": False},
    "llm": {"id": "llm", "name": "Language model (evidence-grounded)", "kind": "web", "tier": "discovery", "official": False},
}

MODULE_SOURCE = {"registry_live": "brreg", "registry": "brreg", "roles": "roles", "locations": "subunits", "group": "group", "financials": "accounts",
                 "financial_history": "account_copies", "geo": "geonorge"}


def website_source(org: str, domain: str, *, verified: bool = True) -> dict[str, Any]:
    return {"id": f"web-{org}", "name": f"Official website ({domain})", "kind": "website", "tier": "primary" if verified else "secondary", "official": verified,
            "url": f"https://{domain}/", "domain": domain}


def job_board_source(org: str, host: str) -> dict[str, Any]:
    dom = registrable_domain(host) or host
    return {"id": f"jobs-{org}-{dom}", "name": f"Company job board ({dom})", "kind": "jobs", "tier": "secondary", "official": False, "url": f"https://{host}/", "domain": dom}


class SourceIndex:
    """Collects the frontend sources referenced by one profile."""

    def __init__(self, org: str, website_domain: str | None):
        self.org = org
        self.domain = website_domain
        self.sources: dict[str, dict[str, Any]] = {}

    def add(self, src: dict[str, Any]) -> str:
        self.sources.setdefault(src["id"], src)
        return src["id"]

    def for_evidence(self, ev: dict[str, Any]) -> str:
        module = ev.get("module") or ""
        sid = ev.get("source_id") or ""
        if module in MODULE_SOURCE:
            return self.add(STATIC_SOURCES[MODULE_SOURCE[module]])
        if sid in STATIC_SOURCES:
            return self.add(STATIC_SOURCES[sid])
        url = ev.get("source_url") or ""
        dom = registrable_domain(host_of(url))
        if module in ("website", "jobs") and self.domain and dom == self.domain:
            return self.add(website_source(self.org, self.domain))
        if module == "jobs" and dom:
            return self.add(job_board_source(self.org, host_of(url)))
        if dom:
            return self.add(website_source(self.org, dom, verified=ev.get("source_class") == "company_owned"))
        return self.add(STATIC_SOURCES["brreg"])

    def tier(self, sid: str) -> str:
        return (self.sources.get(sid) or {}).get("tier", "secondary")


def document_title(ev: dict[str, Any], legal_name: str | None) -> str | None:
    if ev.get("document_title"):
        return ev["document_title"]
    module = ev.get("module")
    name = legal_name or ""
    return {
        "registry_live": f"Enhetsregisteret — {name}", "registry": f"Enhetsregisteret (bulk snapshot) — {name}", "roles": f"Roller — {name}",
        "locations": f"Underenheter — {name}", "group": f"Konsernstruktur — {name}", "financials": f"Årsregnskap — {name}",
        "financial_history": f"Årsregnskap (kopi) — {name}",
    }.get(module or "", None)


def to_frontend_evidence(ev: dict[str, Any], index: SourceIndex, legal_name: str | None, *, period: str | None = None, stated: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": ev["id"], "sourceId": index.for_evidence(ev), "url": ev.get("source_url") or None, "retrievedAt": ev.get("retrieved_at") or "",
        "excerpt": ev.get("claim_span") or None, "documentTitle": document_title(ev, legal_name),
    }
    lang = ev.get("excerpt_language")
    if lang in ("no", "en"):
        out["excerptLanguage"] = lang
    if ev.get("translation"):
        out["excerptTranslation"] = ev["translation"]
    if ev.get("page"):
        out["page"] = ev["page"]
    if period:
        out["reportingPeriod"] = period
    if stated is not None:
        out["statedValue"] = str(stated)
    return {k: v for k, v in out.items() if v is not None}
