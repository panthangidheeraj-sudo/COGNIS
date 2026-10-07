"""Credentialed or access-restricted sources.

Each connector implements the interface, configuration and graceful failure.
Without credentials (or permission) it reports ``not_configured`` and the run
continues. When configured, responses are only used after an exact
organisation-number match; values never override official filings.
"""
from __future__ import annotations

import os
from typing import Any

from ..evidence.models import ModuleResult
from ..identity.model import CanonicalIdentity
from .base import ConnectorContext, module_from_fetch, not_run

PROFF_API_BASE = os.environ.get("PROFF_API_BASE", "https://api.proff.no/api")
DOFFIN_API_BASE = os.environ.get("DOFFIN_API_BASE", "https://api.doffin.no/public/v2")
PATENTSTYRET_API_BASE = os.environ.get("PATENTSTYRET_API_BASE", "https://api.patentstyret.no")


def _find(payload: Any, *keys: str) -> Any:
    """Depth-first lookup of the first matching key (tolerant to provider schema drift)."""
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key in keys:
                if key in item and item[key] not in (None, "", []):
                    return item[key]
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None


async def proff_company(ctx: ConnectorContext) -> ModuleResult:
    s = ctx.settings
    if not (s.enable_proff and s.proff_api_key):
        return not_run("proff", source_id="proff", source_name="Proff.no", source_class="licensed_business_database", state="not_applicable",
                       note="not_configured: Proff requires a licensed API key (PROFF_API_KEY) and ENABLE_PROFF=true.", tier="B")
    url = f"{PROFF_API_BASE}/companies/register/NO/{ctx.org_number}"
    res = await ctx.fetch(url, connector="proff", headers={"Authorization": f"Token {s.proff_api_key}"}, accept="application/json", expect="json", optional=True,
                          cache_ttl=s.cache_ttl_registry_seconds)
    body = res.json() if res.ok else None
    org = str(_find(body, "organisationNumber", "organisasjonsnummer", "orgnr") or "")
    value = None
    if body and org.replace(" ", "") == ctx.org_number:
        value = {"name": _find(body, "name", "companyName", "navn"), "employees": _find(body, "numberOfEmployees", "employees"),
                 "revenue": _find(body, "revenue", "operatingRevenue", "salgsinntekter"), "accounts_year": _find(body, "accountsYear", "year")}
    mod = module_from_fetch("proff", source_id="proff", source_name="Proff.no", source_class="licensed_business_database", result=res, value=value, raw=body, tier="B")
    if res.ok and value is None:
        mod.state, mod.note = "ambiguous", "Response did not carry the exact organisation number; not used."
    return mod


async def doffin_notices(ctx: ConnectorContext, identity: CanonicalIdentity) -> ModuleResult:
    s = ctx.settings
    if not (s.enable_doffin and s.doffin_api_key):
        return not_run("procurement", source_id="doffin", source_name="Doffin", source_class="official_procurement", state="not_applicable",
                       note="not_configured: Doffin's API requires a subscription key (DOFFIN_API_KEY) and access review.")
    url = f"{DOFFIN_API_BASE}/search"
    res = await ctx.fetch(url, connector="doffin", params={"searchString": ctx.org_number, "numHitsPerPage": 20}, headers={"Ocp-Apim-Subscription-Key": s.doffin_api_key or ""},
                          accept="application/json", expect="json", optional=True, cache_ttl=s.cache_ttl_search_seconds)
    body = res.json() if res.ok else None
    hits = []
    for notice in (_find(body, "hits", "notices", "results") or []):
        if ctx.org_number in str(notice):
            hits.append({"id": _find(notice, "id", "noticeId"), "title": _find(notice, "heading", "title"), "published": _find(notice, "publicationDate", "issueDate"),
                         "buyer": _find(notice, "buyer", "contractingAuthority")})
    return module_from_fetch("procurement", source_id="doffin", source_name="Doffin", source_class="official_procurement", result=res, value={"notices": hits}, raw=body)


async def patentstyret_rights(ctx: ConnectorContext, identity: CanonicalIdentity) -> ModuleResult:
    s = ctx.settings
    if not (s.enable_patentstyret and s.patentstyret_api_key):
        return not_run("ip", source_id="patentstyret", source_name="Patentstyret", source_class="official_ip_registry", state="not_applicable",
                       note="not_configured: Patentstyret's API requires a subscription key (PATENTSTYRET_API_KEY) and access review.")
    url = f"{PATENTSTYRET_API_BASE}/search"
    res = await ctx.fetch(url, connector="patentstyret", params={"applicant": identity.legal_name, "orgnr": ctx.org_number},
                          headers={"Ocp-Apim-Subscription-Key": s.patentstyret_api_key or ""}, accept="application/json", expect="json", optional=True)
    body = res.json() if res.ok else None
    rights = [r for r in (_find(body, "results", "items", "hits") or []) if ctx.org_number in str(r)]
    return module_from_fetch("ip", source_id="patentstyret", source_name="Patentstyret", source_class="official_ip_registry", result=res, value={"rights": rights}, raw=body)


def linkedin_module() -> ModuleResult:
    return not_run("linkedin", source_id="linkedin", source_name="LinkedIn", source_class="company_linked_social_profile", state="blocked",
                   note="Automated LinkedIn collection is not permitted; only profile links published by the verified company website are used.", tier="B")


def shareholder_module() -> ModuleResult:
    return not_run("shareholders", source_id="skatteetaten", source_name="Skatteetaten — aksjonærregisteret", source_class="official_shareholder_register",
                   state="not_applicable", note="Shareholder register data is available only by formal request (days); not a runtime source.")


# ------------------------------------------------------------- industry router --
INDUSTRY_ROUTES: list[tuple[tuple[str, ...], str, str]] = [
    (("64", "65", "66"), "finanstilsynet", "Finanstilsynet — virksomhetsregisteret (licensed financial entities)"),
    (("41", "42", "43"), "dibk", "DiBK — sentral godkjenning (construction approvals)"),
    (("10", "11", "56", "01.4", "75"), "mattilsynet", "Mattilsynet (food and animal businesses)"),
    (("50", "52.22", "30.1"), "sjofartsdirektoratet", "Sjøfartsdirektoratet — ship registers"),
    (("03",), "fiskeridirektoratet", "Fiskeridirektoratet (fisheries and aquaculture licences)"),
    (("35",), "nve", "NVE (energy licences)"),
    (("06", "09.1", "49.5"), "sokkeldirektoratet", "Sokkeldirektoratet / Havtil (petroleum)"),
    (("61",), "nkom", "Nkom (electronic communications providers)"),
    (("51", "52.23"), "luftfartstilsynet", "Luftfartstilsynet (aviation)"),
    (("21", "46.46", "47.73"), "dmp", "Direktoratet for medisinske produkter"),
    (("49.1", "49.2"), "jernbanetilsynet", "Statens jernbanetilsyn (rail)"),
    (("49.3", "49.4"), "statens_vegvesen", "Statens vegvesen — løyver (road transport licences)"),
]


def applicable_registries(industry_code: str | None) -> list[dict[str, str]]:
    code = industry_code or ""
    out = []
    for prefixes, key, name in INDUSTRY_ROUTES:
        if any(code.startswith(p) for p in prefixes):
            out.append({"registry": key, "name": name})
    return out


def industry_module(identity: CanonicalIdentity, enabled: bool) -> ModuleResult:
    routes = applicable_registries(identity.industry_code)
    if not routes:
        return not_run("industry", source_id="industry", source_name="Sector registries", source_class="official_sector_registry", state="not_applicable",
                       note="No sector registry applies to this industry code.")
    state = "not_applicable" if not enabled else "not_available"
    note = ("Applicable sector registries: " + "; ".join(r["name"] for r in routes) +
            (". Sector connectors are disabled pending access review." if not enabled else ". No reviewed connector is available for these registries yet."))
    mod = not_run("industry", source_id="industry", source_name="Sector registries", source_class="official_sector_registry", state=state, note=note)
    mod.value = {"applicable": routes}
    return mod
