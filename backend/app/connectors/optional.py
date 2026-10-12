"""Access-restricted sources that are reported, not scraped.

Paid sources are not part of COGNIS: Proff's company data is covered by the free official registers
(``capabilities.py``) and procurement comes from free sources (``procurement.py``). What remains here is reported
per run so the profile can say why a capability is empty: Patentstyret (subscription key, off by default),
LinkedIn (not collected), the shareholder register (formal request only) and sector registries (pending review).
"""
from __future__ import annotations

import os
from typing import Any

from ..evidence.models import ModuleResult
from ..identity.model import CanonicalIdentity
from .base import ConnectorContext, module_from_fetch, not_run

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
