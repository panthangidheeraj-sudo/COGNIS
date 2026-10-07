"""Brønnøysundregistrene connectors (Enhetsregisteret + Regnskapsregisteret).

URL templates are identical to the Signalpost starter kit so evaluator-owned
snapshot replays resolve to the same keys. Normalisers that feed change
detection (``normalize_entity`` / ``normalize_financials`` / ``normalize_roles``
/ ``normalize_locations``) keep the starter's output shape.
"""
from __future__ import annotations

from typing import Any

from ..core.util import clean_ws, date_only
from ..evidence.models import ModuleResult
from ..identity.model import CanonicalIdentity, identity_from_entity
from .base import ConnectorContext, module_from_fetch, not_run

BRREG_ENTITY = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
BRREG_SUBUNIT = "https://data.brreg.no/enhetsregisteret/api/underenheter/{org}"
BRREG_ROLES = BRREG_ENTITY + "/roller"
BRREG_GROUP = "https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}"
BRREG_SUBUNITS = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000"
BRREG_ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
BRREG_ACCOUNT_YEARS = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar"
BRREG_ACCOUNT_PDF = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}"
BRREG_SEARCH = "https://data.brreg.no/enhetsregisteret/api/enheter"
BRREG_PUBLIC_PAGE = "https://virksomhet.brreg.no/nb/oppslag/enheter/{org}"

SRC = {
    "registry_live": ("brreg", "Brønnøysundregistrene — Enhetsregisteret", "official_registry_live"),
    "registry": ("brreg", "Brønnøysundregistrene — Enhetsregisteret (bulk snapshot)", "official_registry_bulk"),
    "roles": ("roles", "Brønnøysundregistrene — roller", "official_roles"),
    "locations": ("subunits", "Brønnøysundregistrene — underenheter", "official_subunits"),
    "group": ("group", "Brønnøysundregistrene — konsernstruktur", "official_group_structure"),
    "financials": ("accounts", "Regnskapsregisteret", "official_annual_accounts"),
    "financial_history": ("account_copies", "Regnskapsregisteret — årsregnskap (kopi)", "official_annual_account_copies"),
}

JSON = "application/json"


def _get(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


# --------------------------------------------------------------- normalisers --
def normalize_entity(body: Any) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    return {
        "organisation_number": body.get("organisasjonsnummer"),
        "name": body.get("navn"),
        "legal_form": _get(body, "organisasjonsform", "kode"),
        "employees": body.get("antallAnsatte"),
        "bankrupt": body.get("konkurs"),
        "liquidating": body.get("underAvvikling"),
        "website": body.get("hjemmeside"),
        "industry": body.get("naeringskode1"),
        "business_address": body.get("forretningsadresse"),
        "postal_address": body.get("postadresse"),
        "latest_submitted_accounts": body.get("sisteInnsendteAarsregnskap"),
    }


def parse_financial_record(item: dict[str, Any]) -> dict[str, Any]:
    period = item.get("regnskapsperiode") or {}
    return {
        "record_id": item.get("id"),
        "account_type": item.get("regnskapstype"),
        "period": period,
        "period_start": date_only(period.get("fraDato")),
        "period_end": date_only(period.get("tilDato")),
        "currency": item.get("valuta"),
        "liquidation_accounts": item.get("avviklingsregnskap"),
        "unaudited": _get(item, "revisjon", "ikkeRevidertAarsregnskap"),
        "audit_opted_out": _get(item, "revisjon", "fravalgRevisjon"),
        "small_company": _get(item, "regnkapsprinsipper", "smaaForetak") if item.get("regnkapsprinsipper") else _get(item, "regnskapsprinsipper", "smaaForetak"),
        "parent_company": _get(item, "virksomhet", "morselskap"),
        "revenue": _get(item, "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter"),
        "operating_expenses": _get(item, "resultatregnskapResultat", "driftsresultat", "driftskostnad", "sumDriftskostnad"),
        "payroll_expenses": _get(item, "resultatregnskapResultat", "driftsresultat", "driftskostnad", "loennskostnad"),
        "operating_result": _get(item, "resultatregnskapResultat", "driftsresultat", "driftsresultat"),
        "net_financial_items": _get(item, "resultatregnskapResultat", "finansresultat", "nettoFinans"),
        "profit_before_tax": _get(item, "resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad"),
        "tax_expense": _get(item, "resultatregnskapResultat", "ordinaertResultatSkattekostnad"),
        "annual_result": _get(item, "resultatregnskapResultat", "aarsresultat"),
        "assets": _get(item, "eiendeler", "sumEiendeler"),
        "fixed_assets": _get(item, "eiendeler", "anleggsmidler", "sumAnleggsmidler"),
        "current_assets": _get(item, "eiendeler", "omloepsmidler", "sumOmloepsmidler"),
        "cash": _get(item, "eiendeler", "sumBankinnskuddOgKontanter"),
        "receivables": _get(item, "eiendeler", "sumFordringer"),
        "equity": _get(item, "egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
        "debt": _get(item, "egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
        "short_term_debt": _get(item, "egenkapitalGjeld", "gjeldOversikt", "kortsiktigGjeld", "sumKortsiktigGjeld"),
        "long_term_debt": _get(item, "egenkapitalGjeld", "gjeldOversikt", "langsiktigGjeld", "sumLangsiktigGjeld"),
        "journal_number": item.get("journalnr"),
    }


def normalize_financials(body: Any) -> dict[str, Any]:
    """Starter-compatible shape (first three records) — used for change detection."""
    records = body if isinstance(body, list) else []
    if not records:
        return {"records": []}
    out = []
    for item in records[:3]:
        out.append({
            "record_id": item.get("id"),
            "account_type": item.get("regnskapstype"),
            "period": item.get("regnskapsperiode"),
            "currency": item.get("valuta"),
            "revenue": _get(item, "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter"),
            "operating_result": _get(item, "resultatregnskapResultat", "driftsresultat", "driftsresultat"),
            "profit_before_tax": _get(item, "resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad"),
            "annual_result": _get(item, "resultatregnskapResultat", "aarsresultat"),
            "assets": _get(item, "eiendeler", "sumEiendeler"),
            "equity": _get(item, "egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
            "debt": _get(item, "egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
        })
    return {"records": out}


def _person_name(person: dict[str, Any]) -> str | None:
    name = person.get("navn") or {}
    if isinstance(name, str):
        return clean_ws(name) or None
    return clean_ws(" ".join(filter(None, [name.get("fornavn"), name.get("mellomnavn"), name.get("etternavn")]))) or None


def _entity_name(entity: dict[str, Any]) -> str | None:
    name = entity.get("navn")
    if isinstance(name, list):
        return clean_ws(" ".join(str(x) for x in name if x)) or None
    return clean_ws(name) or None


def normalize_roles(body: Any) -> dict[str, Any]:
    """Starter-compatible roles list (birth dates are never read)."""
    roles = []
    for group in body.get("rollegrupper", []) if isinstance(body, dict) else []:
        changed = group.get("sistEndret")
        for item in group.get("roller", []) or []:
            person = item.get("person") or {}
            entity = item.get("enhet") or {}
            display = (_person_name(person) if person else None) or (_entity_name(entity) if entity else None)
            roles.append({
                "name": display,
                "organisation_number": entity.get("organisasjonsnummer"),
                "role_code": _get(item, "type", "kode"),
                "role": _get(item, "type", "beskrivelse"),
                "group_code": _get(group, "type", "kode"),
                "group": _get(group, "type", "beskrivelse"),
                "last_changed": changed,
                "inactive": bool(item.get("avregistrert")),
            })
    return {"roles": roles}


def rich_roles(body: Any) -> list[dict[str, Any]]:
    out = []
    for group in body.get("rollegrupper", []) if isinstance(body, dict) else []:
        changed = date_only(group.get("sistEndret"))
        for item in group.get("roller", []) or []:
            person = item.get("person") or {}
            entity = item.get("enhet") or {}
            out.append({
                "kind": "person" if person else "organization",
                "name": _person_name(person) if person else _entity_name(entity),
                "organisation_number": entity.get("organisasjonsnummer"),
                "entity_deleted": bool(entity.get("erSlettet")),
                "deceased": bool(person.get("erDoed")),
                "role_code": _get(item, "type", "kode"),
                "role": _get(item, "type", "beskrivelse"),
                "group_code": _get(group, "type", "kode"),
                "group": _get(group, "type", "beskrivelse"),
                "group_last_changed": changed,
                "inactive": bool(item.get("avregistrert")) or bool(item.get("fratraadt")),
                "resigned": bool(item.get("fratraadt")),
                "order": item.get("rekkefolge"),
                "elected_by": _get(item, "valgtAv", "beskrivelse"),
            })
    return out


def normalize_locations(body: Any) -> dict[str, Any]:
    rows = _get(body, "_embedded", "underenheter") or []
    return {"locations": [{
        "organisation_number": item.get("organisasjonsnummer"),
        "name": item.get("navn"),
        "address": item.get("beliggenhetsadresse") or item.get("postadresse"),
        "industry": item.get("naeringskode1"),
        "employees": item.get("antallAnsatte"),
    } for item in rows]}


def rich_locations(body: Any) -> list[dict[str, Any]]:
    rows = _get(body, "_embedded", "underenheter") or []
    out = []
    for item in rows:
        out.append({
            "organisation_number": item.get("organisasjonsnummer"),
            "name": clean_ws(item.get("navn")),
            "address": item.get("beliggenhetsadresse") or item.get("postadresse") or {},
            "industry": item.get("naeringskode1"),
            "employees": item.get("antallAnsatte") if item.get("harRegistrertAntallAnsatte") is not False else None,
            "started": date_only(item.get("oppstartsdato")),
            "registered_at": date_only(item.get("registreringsdatoEnhetsregisteret")),
            "closed": date_only(item.get("nedleggelsesdato")),
            "website": item.get("hjemmeside"),
            "deleted": bool(item.get("slettedato")),
        })
    return out


def normalize_financial_history(body: Any, org: str) -> dict[str, Any]:
    years = sorted({str(y) for y in body if str(y).isdigit()}) if isinstance(body, list) else []
    return {"years": years, "pdfs": [{"year": y, "url": BRREG_ACCOUNT_PDF.format(org=org, year=y)} for y in reversed(years)]}


# --------------------------------------------------------------- connectors --
def _src(module: str) -> dict[str, str]:
    sid, name, cls = SRC[module]
    return {"source_id": sid, "source_name": name, "source_class": cls}


async def fetch_entity(ctx: ConnectorContext, *, optional: bool = False) -> tuple[ModuleResult, CanonicalIdentity | None]:
    """Live entity record. Falls back to the sub-unit register when the number is an establishment."""
    org = ctx.org_number
    url = BRREG_ENTITY.format(org=org)
    res = await ctx.fetch(url, connector="brreg", optional=optional, accept=JSON, expect="json", cache_ttl=ctx.settings.cache_ttl_registry_seconds)
    body = None
    if res.ok or (res.classification == "gone" and res.body):
        try:
            body = res.json()
        except ValueError:
            body = None
    if res.ok and isinstance(body, dict):
        identity = identity_from_entity(org, body, source_url=url, retrieved_at=res.retrieved_at, content_sha256=res.content_sha256)
        return module_from_fetch("registry_live", **_src("registry_live"), result=res, value=normalize_entity(body), raw=body), identity
    if res.classification == "gone":
        identity = identity_from_entity(org, body, source_url=url, retrieved_at=res.retrieved_at, content_sha256=res.content_sha256) if isinstance(body, dict) and body.get("navn") else None
        if identity:
            identity.status, identity.status_label = "deleted", "Deleted from the register"
        mod = module_from_fetch("registry_live", **_src("registry_live"), result=res, value=normalize_entity(body) if isinstance(body, dict) else None, raw=body,
                                note="The register reports this unit as deleted (HTTP 410).")
        mod.state = "available" if identity else "not_available"
        return mod, identity
    if res.classification == "not_found":
        sub = await ctx.fetch(BRREG_SUBUNIT.format(org=org), connector="brreg", optional=optional, accept=JSON, expect="json", cache_ttl=ctx.settings.cache_ttl_registry_seconds)
        if sub.ok:
            sub_body = sub.json()
            if isinstance(sub_body, dict):
                identity = identity_from_entity(org, sub_body, source_url=sub.url, retrieved_at=sub.retrieved_at, content_sha256=sub.content_sha256)
                mod = module_from_fetch("registry_live", **_src("registry_live"), result=sub, value=normalize_entity(sub_body), raw=sub_body,
                                        note="Organisation number is a registered establishment (underenhet).")
                mod.requests += 1
                return mod, identity
    return module_from_fetch("registry_live", **_src("registry_live"), result=res), None


async def fetch_roles(ctx: ConnectorContext, *, optional: bool = False) -> ModuleResult:
    url = BRREG_ROLES.format(org=ctx.org_number)
    res = await ctx.fetch(url, connector="brreg", optional=optional, accept=JSON, expect="json", cache_ttl=ctx.settings.cache_ttl_registry_seconds)
    body = res.json() if res.ok else None
    value = normalize_roles(body) if isinstance(body, dict) else None
    mod = module_from_fetch("roles", **_src("roles"), result=res, value=value, raw=body)
    if res.ok and not (value or {}).get("roles"):
        mod.state, mod.note = "not_available", "The register lists no roles for this unit."
    if res.classification == "not_found":
        mod.note = "The register lists no roles for this unit."
    return mod


async def fetch_locations(ctx: ConnectorContext, *, optional: bool = False) -> ModuleResult:
    url = BRREG_SUBUNITS.format(org=ctx.org_number)
    res = await ctx.fetch(url, connector="brreg", optional=optional, accept=JSON, expect="json", cache_ttl=ctx.settings.cache_ttl_registry_seconds)
    body = res.json() if res.ok else None
    value = normalize_locations(body) if res.ok else None
    mod = module_from_fetch("locations", **_src("locations"), result=res, value=value, raw=body)
    if res.ok:
        # A checked source with zero registered establishments is a real (available) answer: count = 0.
        mod.note = None if (value or {}).get("locations") else "No registered establishments (underenheter)."
    return mod


async def fetch_group(ctx: ConnectorContext, identity: CanonicalIdentity | None, *, optional: bool = True) -> ModuleResult:
    url = BRREG_GROUP.format(org=ctx.org_number)
    if identity is not None and identity.in_group is False:
        return not_run("group", **_src("group"), state="not_applicable", note="The register reports the company is not part of a group (erIKonsern=false).", url=url)
    if not ctx.settings.enable_group_structure:
        return not_run("group", **_src("group"), state="not_applicable", note="Group-structure lookup disabled by configuration.", url=url)
    res = await ctx.fetch(url, connector="brreg", optional=optional, accept=JSON, expect="json", cache_ttl=ctx.settings.cache_ttl_registry_seconds)
    body = res.json() if res.ok else None
    return module_from_fetch("group", **_src("group"), result=res, value=body if isinstance(body, dict) else None, raw=body)


async def fetch_financials(ctx: ConnectorContext, identity: CanonicalIdentity | None, *, optional: bool = False) -> ModuleResult:
    url = BRREG_ACCOUNTS.format(org=ctx.org_number)
    if identity is not None and identity.source == "live" and not identity.latest_accounts_year and identity.legal_form not in ("AS", "ASA"):
        return not_run("financials", **_src("financials"), state="not_available", url=url,
                       note="The register reports no submitted annual accounts for this unit (sisteInnsendteAarsregnskap is empty).")
    res = await ctx.fetch(url, connector="brreg_accounts", optional=optional, accept=JSON, expect="json", cache_ttl=ctx.settings.cache_ttl_registry_seconds)
    body = res.json() if res.ok else None
    records = [parse_financial_record(item) for item in body] if isinstance(body, list) else []
    mod = module_from_fetch("financials", **_src("financials"), result=res, value=normalize_financials(body) if res.ok else None, raw={"records": records} if res.ok else None)
    if res.ok and not records:
        mod.state, mod.note = "not_available", "Regnskapsregisteret returned no annual-account records."
    if res.classification == "not_found":
        mod.note = "Regnskapsregisteret has no annual accounts for this unit (a 404 is not a zero)."
    return mod


async def fetch_financial_history(ctx: ConnectorContext, identity: CanonicalIdentity | None, *, optional: bool = True) -> ModuleResult:
    url = BRREG_ACCOUNT_YEARS.format(org=ctx.org_number)
    if not ctx.settings.enable_financial_history:
        return not_run("financial_history", **_src("financial_history"), state="not_applicable", note="Filing-history lookup disabled by configuration.", url=url)
    if identity is not None and identity.source == "live" and not identity.latest_accounts_year:
        return not_run("financial_history", **_src("financial_history"), state="not_available", url=url, note="No submitted annual accounts are registered.")
    res = await ctx.fetch(url, connector="brreg_account_copies", optional=optional, accept=JSON, expect="json", interval_key="brreg-account-copies",
                          cache_ttl=ctx.settings.cache_ttl_registry_seconds)
    body = res.json() if res.ok else None
    value = normalize_financial_history(body, ctx.org_number) if res.ok else None
    mod = module_from_fetch("financial_history", **_src("financial_history"), result=res, value=value, raw=body)
    if res.ok and not (value or {}).get("years"):
        mod.state, mod.note = "not_available", "No filed annual-account copies are listed."
    return mod


async def search_entities(ctx: ConnectorContext, params: dict[str, Any]) -> tuple[list[dict[str, Any]], int, str | None]:
    """Enhetsregisteret search (used by Discover / global search). Returns (rows, total, error)."""
    res = await ctx.fetch(BRREG_SEARCH, connector="brreg_search", params=params, accept=JSON, expect="json", cache_ttl=3600, optional=True)
    if not res.ok:
        return [], 0, res.error or res.classification
    body = res.json() or {}
    rows = _get(body, "_embedded", "enheter") or []
    total = int(_get(body, "page", "totalElements") or len(rows))
    return rows, total, None
