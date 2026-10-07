"""Norid RDAP (.no domains). Used only as an identity signal.

Norid discloses the holder's organisation number for organisation-held
domains in some RDAP/whois views. We search the RDAP JSON for a checksum-valid
organisation number deterministically and never infer anything else from it.
"""
from __future__ import annotations

import json

from ..evidence.models import ModuleResult
from ..identity.normalization import find_org_numbers, org_checksum_ok
from .base import ConnectorContext, module_from_fetch, not_run

NORID_RDAP = "https://rdap.norid.no/domain/{domain}"


def holder_org_from_rdap(body: object) -> str | None:
    text = json.dumps(body, ensure_ascii=False)
    numbers = [n for n, _ in find_org_numbers(text) if org_checksum_ok(n)]
    for entity in (body or {}).get("entities", []) if isinstance(body, dict) else []:
        roles = entity.get("roles") or []
        if "registrant" in roles:
            sub = json.dumps(entity, ensure_ascii=False)
            found = [n for n, _ in find_org_numbers(sub)]
            if found:
                return found[0]
    return numbers[0] if len(set(numbers)) == 1 else None


async def lookup_domain(ctx: ConnectorContext, domain: str) -> tuple[ModuleResult, str | None]:
    url = NORID_RDAP.format(domain=domain)
    if not ctx.settings.enable_norid:
        return not_run("norid", source_id="norid", source_name="Norid RDAP", source_class="domain_registry", state="not_applicable", note="Disabled by configuration.", url=url, tier="B"), None
    if not domain.endswith(".no"):
        return not_run("norid", source_id="norid", source_name="Norid RDAP", source_class="domain_registry", state="not_applicable", note="Not a .no domain.", url=url, tier="B"), None
    res = await ctx.fetch(url, connector="norid", accept="application/rdap+json,application/json", expect="json", cache_ttl=ctx.settings.cache_ttl_registry_seconds, optional=True)
    body = res.json() if res.ok else None
    holder = holder_org_from_rdap(body) if body else None
    mod = module_from_fetch("norid", source_id="norid", source_name="Norid RDAP", source_class="domain_registry", result=res, value={"domain": domain, "holder_org": holder}, raw=body, tier="B")
    return mod, holder
