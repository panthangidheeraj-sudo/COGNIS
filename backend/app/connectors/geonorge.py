"""Kartverket / Geonorge address search — geocodes the registered address for maps."""
from __future__ import annotations

from ..evidence.models import ModuleResult
from ..identity.model import CanonicalIdentity
from .base import ConnectorContext, module_from_fetch, not_run

GEONORGE_ADDRESSES = "https://ws.geonorge.no/adresser/v1/sok"
GEONORGE_MUNICIPALITY = "https://ws.geonorge.no/kommuneinfo/v1/kommuner/{number}"


async def geocode(ctx: ConnectorContext, identity: CanonicalIdentity) -> ModuleResult:
    addr = identity.business_address or {}
    lines = addr.get("adresse") or []
    if not ctx.settings.enable_geocoding:
        return not_run("geo", source_id="geonorge", source_name="Kartverket — Geonorge", source_class="official_geodata", state="not_applicable", note="Geocoding disabled.")
    street = next((line for line in reversed(lines) if any(ch.isdigit() for ch in line) and not line.lower().startswith(("postboks", "c/o", "pb "))), None)
    if street and addr.get("postnummer"):
        res = await ctx.fetch(GEONORGE_ADDRESSES, connector="geonorge", params={"sok": street, "postnummer": addr.get("postnummer"), "treffPerSide": 1, "utkoordsys": 4258},
                              accept="application/json", expect="json", cache_ttl=30 * 24 * 3600, optional=True)
        if res.ok:
            rows = (res.json() or {}).get("adresser") or []
            point = (rows[0] or {}).get("representasjonspunkt") if rows else None
            if point and point.get("lat") is not None:
                return module_from_fetch("geo", source_id="geonorge", source_name="Kartverket — Geonorge", source_class="official_geodata", result=res,
                                         value={"lat": round(float(point["lat"]), 5), "lon": round(float(point["lon"]), 5), "precision": "address", "matched": rows[0].get("adressetekst")})
    if identity.municipality_number:
        res = await ctx.fetch(GEONORGE_MUNICIPALITY.format(number=identity.municipality_number), connector="geonorge", accept="application/json", expect="json", cache_ttl=90 * 24 * 3600, optional=True)
        if res.ok:
            body = res.json() or {}
            point = body.get("punktIOmrade") or {}
            coords = point.get("coordinates") if isinstance(point, dict) else None
            if coords and len(coords) == 2:
                return module_from_fetch("geo", source_id="geonorge", source_name="Kartverket — Geonorge", source_class="official_geodata", result=res,
                                         value={"lat": round(float(coords[1]), 5), "lon": round(float(coords[0]), 5), "precision": "municipality"})
        return module_from_fetch("geo", source_id="geonorge", source_name="Kartverket — Geonorge", source_class="official_geodata", result=res, value=None)
    return not_run("geo", source_id="geonorge", source_name="Kartverket — Geonorge", source_class="official_geodata", state="not_available", note="No address to geocode.")
