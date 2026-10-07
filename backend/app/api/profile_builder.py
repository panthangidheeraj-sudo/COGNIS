"""Research record → frontend ``CompanyProfile`` (src/types/company.ts).

Only published claims become facts; explicit absences become ``not_available``
/ ``blocked`` / ``ambiguous`` facts or section messages. Nothing is invented:
a section without evidence says so, in the words the backend chose.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..core.util import currency_unit, format_int, format_money, normalize_currency, now_iso, stated_currencies, title_case_no
from ..identity.model import COUNTIES, LEGAL_FORMS
from .sources import SourceIndex, to_frontend_evidence

PENDING = "Not researched yet. Run research to gather this area from public sources."
STATUS_MAP = {"active": "active", "bankruptcy": "bankruptcy", "under_liquidation": "under_liquidation", "forced_dissolution": "under_liquidation",
              "deleted": "dissolved"}
SERIES = [("revenue", "revenue", "Revenue"), ("operating_result", "operating_result", "Operating result"), ("annual_result", "annual_result", "Annual result"),
          ("total_assets", "total_assets", "Total assets"), ("equity", "equity", "Equity"), ("debt", "debt", "Total debt"),
          ("cash_and_bank", "cash", "Cash and bank deposits")]
ROLE_GROUP = {"ceo": "executive", "business_manager": "executive", "board_chair": "board", "deputy_chair": "board", "board_member": "board",
              "deputy_board_member": "board", "board_observer": "board", "proprietor": "founder", "general_partner": "other", "partner": "other"}
ROLE_FIELDS = ("ceo", "business_manager", "board_chair", "deputy_chair", "board_member", "deputy_board_member", "board_observer", "proprietor", "partner",
               "general_partner", "co_owner", "auditor", "accountant", "contact_person", "norwegian_representative", "estate_administrator")
PAGE_TITLES = {"about": "About", "products": "Products & services", "contact": "Contact", "careers": "Careers", "news": "News", "investors": "Investor relations",
               "sustainability": "Sustainability"}
NETWORKS = {"linkedin", "facebook", "x", "instagram", "youtube", "github"}


def _round1(v: float) -> float:
    return round(v * 10) / 10


CURRENCY_NOT_STATED_NOTE = "The filing does not state a currency; the amount is shown exactly as filed, without a currency label."


def _year(period: str | None) -> int | None:
    m = re.search(r"(\d{4})", period or "")
    return int(m.group(1)) if m else None


class Builder:
    def __init__(self, record: dict[str, Any], *, changes: list[dict[str, Any]] | None = None, previous_at: str | None = None, artifact_id: str | None = None,
                 tags: list[str] | None = None):
        self.r = record
        self.org = record["organisation_number"]
        self.identity = record.get("identity") or {}
        self.legal_name = self.identity.get("legal_name") or self.org
        self.claims = record.get("claims") or []
        self.absences = {a["field"]: a for a in record.get("absences") or []}
        self.modules = record.get("modules") or {}
        self.ev_by_id = {e["id"]: e for e in record.get("evidence") or []}
        self.website = record.get("website") or {}
        self.domain = self.website.get("domain") if self.website.get("verified") else None
        self.sources = SourceIndex(self.org, self.domain)
        self.facts: list[tuple[dict[str, Any], str]] = []  # (fact, section)
        self.section = "identity"
        self.changes = changes or []
        self.previous_at = previous_at
        self.artifact_id = artifact_id
        self.tags = tags or []
        self.researched = record.get("mode") not in ("registry",)
        self.researched_at = record.get("completed_at")
        self.by_field: dict[str, list[dict[str, Any]]] = {}
        for c in self.claims:
            self.by_field.setdefault(c["field"], []).append(c)

    # ---------------------------------------------------------------- facts --
    def first(self, field: str) -> dict[str, Any] | None:
        items = self.by_field.get(field) or []
        return items[0] if items else None

    def evidence_for(self, claim: dict[str, Any], *, period: str | None = None) -> list[dict[str, Any]]:
        out = []
        for eid in claim.get("evidence_ids") or []:
            ev = self.ev_by_id.get(eid)
            if ev:
                out.append(to_frontend_evidence(ev, self.sources, self.legal_name, period=period))
        return out

    def fact(self, path: str, label: str, claim: dict[str, Any] | None, *, value: Any = "__claim__", display: str | None = None, unit: str | None = None,
             currency: str | None = None, period: str | None = None, freshness: str | None = None, absent: str | None = None, note: str | None = None,
             fid: str | None = None) -> dict[str, Any]:
        """Build a frontend Fact from a published claim (or an explicit absence)."""
        if claim is None:
            ab = self.absences.get(absent or "") if absent else None
            status = {"blocked": "blocked", "ambiguous": "ambiguous", "failed": "failed"}.get((ab or {}).get("availability"), "not_available")
            if not self.researched and absent in ("official_website", "business_description", "open_positions_count"):
                status = "pending"
            f = {"id": fid or f"{self.org}:{path}", "field": path, "label": label, "status": status, "value": None, "evidenceState": "unverified", "evidence": [],
                 "note": note or (ab or {}).get("note") or ("Not researched yet." if status == "pending" else "Not established in the searched sources.")}
            self.facts.append((f, self.section))
            return f
        evidence = self.evidence_for(claim, period=period)
        v = claim["value"] if value == "__claim__" else value
        conflict = None
        if claim.get("conflict"):
            cands = []
            for cand in claim["conflict"]["candidates"]:
                ev_ids = cand.get("evidence_ids") or []
                ev = self.ev_by_id.get(ev_ids[0]) if ev_ids else None
                sid = self.sources.for_evidence(ev) if ev else "brreg"
                if ev and not any(e["id"] == ev["id"] for e in evidence):
                    evidence.append(to_frontend_evidence(ev, self.sources, self.legal_name, period=period, stated=cand["value"]))
                item = {"sourceId": sid, "value": cand["value"] if isinstance(cand["value"], (str, int, float, bool)) else str(cand["value"]),
                        "reportingPeriod": period, "evidenceId": ev_ids[0] if ev_ids else ""}
                if cand.get("currency") and isinstance(cand["value"], (int, float)) and not isinstance(cand["value"], bool):
                    # a candidate may be stated in a different currency than the winner: label it with its own, never with the fact's
                    item["currency"] = cand["currency"]
                    if cand["currency"] != claim.get("currency"):
                        item["displayValue"] = format_money(cand["value"], cand["currency"])
                cands.append(item)
            conflict = {"reason": claim["conflict"].get("reason"), "candidates": cands}
        primary = [e for e in evidence if self.sources.tier(e["sourceId"]) == "primary"]
        distinct = {e["sourceId"] for e in evidence}
        state = "conflict" if conflict else ("verified" if len(distinct) >= 2 and primary else "primary" if primary else "secondary" if evidence else "unverified")
        f: dict[str, Any] = {
            "id": fid or f"{self.org}:{path}", "field": path, "label": label, "status": "verified", "value": v, "evidenceState": state, "evidence": evidence,
            "verifiedAt": evidence[0]["retrievedAt"] if evidence else self.researched_at,
            "freshness": freshness or ("current" if claim.get("current", True) else "historical"),
        }
        if display is not None:
            f["displayValue"] = display
        if unit:
            f["unit"] = unit
        if currency:
            f["currency"] = currency
        if period:
            f["reportingPeriod"] = period
        if conflict:
            f["conflict"] = conflict
        if note:
            f["note"] = note
        self.facts.append((f, self.section))
        return f

    def money_fact(self, path: str, label: str, claim: dict[str, Any], *, period: str | None = None, freshness: str | None = None,
                   fid: str | None = None) -> dict[str, Any]:
        """A monetary fact in the currency its own filing states (``claim['currency']``); ``displayValue`` is built from that same code.

        Without a stated currency there is no unit/currency label at all (never an assumed NOK) and the fact says so in ``note``.
        """
        currency = normalize_currency(claim.get("currency"))
        return self.fact(path, label, claim, unit=currency, currency=currency, period=period, freshness=freshness, display=format_money(claim["value"], currency),
                         note=None if currency else CURRENCY_NOT_STATED_NOTE, fid=fid)

    # --------------------------------------------------------------- build --
    def build(self) -> dict[str, Any]:
        ident = self.identity
        self.section = "identity"
        identity = self.identity_section()
        self.section = "overview"
        description = self.description()
        self.section = "financials"
        financials = self.financials()
        self.section = "people"
        people = self.people()
        self.section = "locations"
        locations = self.locations(identity)
        self.section = "website"
        website = self.website_section(identity, description)
        self.section = "hiring"
        hiring = self.hiring()
        self.section = "activity"
        activity = self.activity()
        self.section = "changes"
        changes = self.changes_section()
        self.section = "relationships"
        relationships = self.relationships(people)
        self.section = "overview"
        key_metrics = self.key_metrics(financials, identity, locations, hiring)
        coverage = self.coverage(financials, people, locations, website, hiring, activity)
        sources = self.source_usage(hiring, activity, changes)
        summary = self.summary()
        geo = (self.modules.get("geo") or {}).get("value") if (self.modules.get("geo") or {}).get("state") == "available" else None
        rev_series = next((s for s in financials["series"] if s["key"] == "revenue"), None)
        latest_rev = rev_series["points"][-1] if rev_series and rev_series["points"] else None
        emp_claim = self.first("registered_employees")
        status = STATUS_MAP.get(ident.get("status") or "", "other")
        company = {
            "orgNumber": self.org, "legalName": self.legal_name, "municipality": title_case_no(ident.get("municipality")) or None,
            "county": ident.get("county") or COUNTIES.get((ident.get("municipality_number") or "")[:2]), "country": "Norway",
            "industry": {"code": ident.get("industry_code"), "description": ident.get("industry_label") or ""} if ident.get("industry_code") else None,
            "status": status, "statusLabel": ident.get("status_label") or status.replace("_", " ").title(),
            "employees": emp_claim["value"] if emp_claim else None, "revenue": {"value": latest_rev["fact"]["value"], "currency": latest_rev["fact"].get("currency") or "", "period": latest_rev["period"]} if latest_rev else None,
            "openPositions": hiring["totalCurrent"], "coverage": coverage, "lastResearchedAt": self.researched_at if self.researched else None,
            "researchState": "researched" if self.researched else "not_researched", "website": self.domain or None,
            "geo": {"lat": geo["lat"], "lon": geo["lon"]} if geo else None, "changeCount": len([c for c in changes["changes"] if c["material"]]), "tags": self.tags,
        }
        if emp_claim and emp_claim.get("as_of"):
            company["employeesPeriod"] = emp_claim["as_of"][:4]
        company = {k: v for k, v in company.items() if v is not None or k in ("employees", "revenue", "openPositions", "lastResearchedAt", "website", "geo")}
        profile = {
            "company": company, "identity": identity, "summary": summary, "keyMetrics": key_metrics, "financials": financials, "people": people,
            "locations": locations, "website": website, "hiring": hiring, "activity": activity, "changes": changes, "relationships": relationships,
            "sources": sources, "sourceIndex": dict(self.sources.sources),
            "quality": {"coverage": coverage, "primarySources": sum(1 for s in sources if s["source"]["tier"] == "primary"),
                        "secondarySources": sum(1 for s in sources if s["source"]["tier"] != "primary"),
                        "conflicts": sum(1 for f, _ in self.facts if f.get("conflict")), "lastRefreshedAt": self.researched_at if self.researched else None},
            "knowns": self.knowns(identity, people, financials, hiring, website),
        }
        if description:
            profile["description"] = description
        if self.artifact_id:
            profile["artifactId"] = self.artifact_id
        return profile

    # ------------------------------------------------------------ sections --
    def identity_section(self) -> dict[str, Any]:
        ident = self.identity
        out: dict[str, Any] = {"orgNumber": self.org}
        out["legalName"] = self.fact("identity.legalName", "Legal name", self.first("legal_name"), absent="legal_name")
        status = self.first("registration_status")
        out["status"] = self.fact("identity.status", "Status", status, value=(status or {}).get("attributes", {}).get("label") or ident.get("status_label") if status else None,
                                  absent="registration_status")
        form = self.first("legal_form")
        if form:
            desc = LEGAL_FORMS.get(form["value"]) or (form.get("attributes") or {}).get("description") or form["value"]
            out["legalForm"] = self.fact("identity.legalForm", "Legal form", form, value=desc if desc == form["value"] or desc.endswith(f"({form['value']})") else f"{desc} ({form['value']})")
        founded = self.first("founded_date")
        if founded:
            out["founded"] = self.fact("identity.founded", "Founded", founded, freshness="historical")
        ind = self.first("industry_label")
        code = self.first("industry_code")
        if ind or code:
            base = ind or code
            text = f"{ind['value']} ({code['value']})" if ind and code else base["value"]
            merged = dict(base)
            merged["evidence_ids"] = list(dict.fromkeys((ind or {}).get("evidence_ids", []) + (code or {}).get("evidence_ids", [])))
            out["industry"] = self.fact("identity.industry", "Industry", merged, value=text)
        addr = self.first("business_address")
        if addr:
            out["registeredAddress"] = self.fact("identity.registeredAddress", "Registered address", addr)
        site = self.first("official_website")
        if site:
            out["website"] = self.fact("identity.website", "Official website", site, value=self.domain or site["value"],
                                       note=None if (self.website.get("origin") == "registry") else "Verified by identity signals on the site itself; the register does not list it.")
        elif self.first("registered_website"):
            reg = self.first("registered_website")
            web_state = (self.modules.get("website") or {}).get("state")
            f = self.fact("identity.website", "Website listed in the register", reg)
            if web_state in ("ambiguous", "blocked", "failed", "not_available") and self.researched:
                f["status"] = {"ambiguous": "ambiguous", "blocked": "blocked", "failed": "failed"}.get(web_state, "verified")
                f["note"] = (self.modules.get("website") or {}).get("note") or "Listed in the register; the site could not be verified as belonging to this company."
            out["website"] = f
        return out

    def description(self) -> dict[str, Any] | None:
        desc = self.first("business_description")
        if not desc:
            return None
        translation = (desc.get("attributes") or {}).get("translation")
        f = self.fact("overview.description", "What the company does", desc, value=translation or desc["value"])
        for ev in f["evidence"]:
            if translation and "excerptTranslation" not in ev:
                ev["excerptTranslation"] = translation
        return f

    def financials(self) -> dict[str, Any]:
        mod = self.modules.get("financials") or {}
        series = []
        for field, key, label in SERIES:
            claims = sorted(self.by_field.get(field) or [], key=lambda c: c.get("reporting_period") or "")
            if not claims:
                continue
            latest = claims[-1].get("reporting_period")
            points = []
            for c in claims:
                period = c.get("period_label") or f"FY{_year(c.get('reporting_period'))}"
                year = _year((c.get("reporting_period") or "").split("/")[-1]) or 0
                fact = self.money_fact(f"financials.{key}.{year}", label, c, period=period, freshness="current" if c.get("reporting_period") == latest else "historical",
                                       fid=f"{self.org}:financials.{key}.{year}")
                points.append({"period": period, "year": year, "fact": fact})
            point_currencies = [pt["fact"].get("currency") for pt in points]
            series.append({"key": key, "label": label, "unit": currency_unit(point_currencies), "currencies": stated_currencies(point_currencies), "points": points})
        if not series:
            state = mod.get("state")
            status = {"blocked": "blocked", "failed": "not_available", "ambiguous": "ambiguous"}.get(state or "", "not_available")
            msg = mod.get("note") or "No filed annual accounts were found for this company."
            if (self.absences.get("revenue") or {}).get("availability") == "not_applicable":
                msg = self.absences["revenue"]["note"]
            return {"status": status, "message": msg, "currency": "", "currencies": [], "series": [], "ratios": [], "searchedSourceIds": ["accounts"]}
        at = {s["key"]: {p["period"]: p["fact"]["value"] for p in s["points"]} for s in series}
        cur_at = {s["key"]: {p["period"]: p["fact"].get("currency") for p in s["points"]} for s in series}

        def same_currency(*pairs: tuple[str, str], stated: bool = False) -> bool:
            """Ratios and growth only mix amounts that are provably in one currency (a ratio of USD to NOK is meaningless; no conversion is applied)."""
            found = {cur_at.get(k, {}).get(per, "?") for k, per in pairs}
            return len(found) == 1 and (not stated or next(iter(found)) not in (None, "?"))

        periods = [p["period"] for p in next((s for s in series if s["key"] == "revenue"), series[0])["points"]]
        defs = [
            ("operating_margin", "Operating margin", "Operating result ÷ Revenue", lambda p, i: (at.get("operating_result", {}).get(p) / at["revenue"][p] * 100)
             if at.get("revenue", {}).get(p) and at.get("operating_result", {}).get(p) is not None and same_currency(("operating_result", p), ("revenue", p)) else None),
            ("profit_margin", "Profit margin", "Annual result ÷ Revenue", lambda p, i: (at.get("annual_result", {}).get(p) / at["revenue"][p] * 100)
             if at.get("revenue", {}).get(p) and at.get("annual_result", {}).get(p) is not None and same_currency(("annual_result", p), ("revenue", p)) else None),
            ("equity_ratio", "Equity ratio", "Equity ÷ Total assets", lambda p, i: (at.get("equity", {}).get(p) / at["total_assets"][p] * 100)
             if at.get("total_assets", {}).get(p) and at.get("equity", {}).get(p) is not None and same_currency(("equity", p), ("total_assets", p)) else None),
            ("revenue_growth", "Revenue growth", "(Revenue FY − Revenue FY−1) ÷ Revenue FY−1", lambda p, i: ((at["revenue"][p] - at["revenue"][periods[i - 1]]) / abs(at["revenue"][periods[i - 1]]) * 100)
             if i > 0 and at.get("revenue", {}).get(periods[i - 1]) and at.get("revenue", {}).get(p) is not None
             and same_currency(("revenue", p), ("revenue", periods[i - 1]), stated=True) else None),
        ]
        ratio_history, ratios = [], []
        for key, label, formula, fn in defs:
            pts = []
            for i, p in enumerate(periods):
                try:
                    v = fn(p, i)
                except (KeyError, ZeroDivisionError, TypeError):
                    v = None
                if v is not None:
                    pts.append({"period": p, "value": _round1(v)})
            if pts:
                ratio_history.append({"key": key, "label": label, "formula": formula, "points": pts})
                last = pts[-1]
                period = f"{periods[periods.index(last['period']) - 1]}→{last['period']}" if key == "revenue_growth" else last["period"]
                if last["period"] == periods[-1]:
                    ratios.append({"key": key, "label": label, "value": last["value"], "period": period, "formula": formula})
        complete = len(series) >= 3 and len(series[0]["points"]) >= 2
        section_currencies = [c for s in series for c in s["currencies"]]
        unit_set = [pt["fact"].get("currency") for s in series for pt in s["points"]]
        return {"status": "available" if complete or series else "partial", "currency": currency_unit(unit_set), "currencies": stated_currencies(section_currencies),
                "latestPeriod": periods[-1] if periods else None, "series": series, "ratios": ratios, "ratioHistory": ratio_history}

    def people(self) -> dict[str, Any]:
        mod = self.modules.get("roles") or {}
        people = []
        i = 0
        for field in ROLE_FIELDS:
            for c in self.by_field.get(field) or []:
                role = c.get("label") or field.replace("_", " ").title()
                fact = self.fact(f"people.{i}", role, c, fid=f"{self.org}:people.{i}")
                people.append({"id": f"{self.org}-p{i}", "name": c["value"], "role": role, "roleGroup": ROLE_GROUP.get(field, "other"), "current": True, "fact": fact})
                i += 1
        if people:
            return {"status": "available", "people": people}
        if not self.researched and mod.get("state") is None:
            return {"status": "pending", "people": [], "message": PENDING}
        status = {"blocked": "blocked", "ambiguous": "ambiguous"}.get(mod.get("state") or "", "not_available")
        return {"status": status, "people": [], "message": mod.get("note") or "No registered roles found."}

    def locations(self, identity: dict[str, Any]) -> dict[str, Any]:
        out = []
        geo = (self.modules.get("geo") or {}).get("value") if (self.modules.get("geo") or {}).get("state") == "available" else None
        reg = identity.get("registeredAddress")
        ident = self.identity
        if reg:
            addr = ident.get("business_address") or {}
            out.append({"id": f"{self.org}-loc-reg", "kind": "registered_address", "label": "Registered address", "address": ", ".join(addr.get("adresse") or []) or reg["value"],
                        "postalCode": addr.get("postnummer"), "municipality": title_case_no(addr.get("kommune") or ident.get("municipality")) or "",
                        "geo": {"lat": geo["lat"], "lon": geo["lon"]} if geo else None, "verified": True, "fact": reg})
        post = self.first("postal_address")
        if post:
            paddr = ident.get("postal_address") or {}
            out.append({"id": f"{self.org}-loc-post", "kind": "postal", "label": "Postal address", "address": post["value"], "postalCode": paddr.get("postnummer"),
                        "municipality": title_case_no(paddr.get("kommune") or paddr.get("poststed")) or "", "verified": True,
                        "fact": self.fact("locations.postal", "Postal address", post)})
        for i, c in enumerate(self.by_field.get("registered_establishment") or []):
            attrs = c.get("attributes") or {}
            out.append({"id": f"{self.org}-loc{i}", "kind": "operating", "label": attrs.get("name") or "Registered establishment", "address": attrs.get("address") or c["value"],
                        "postalCode": attrs.get("postal_code"), "municipality": attrs.get("municipality") or "", "verified": True,
                        "fact": self.fact(f"locations.{i}", "Registered establishment", c, fid=f"{self.org}:locations.{i}")})
        for loc in out:
            if loc.get("geo") is None:
                loc.pop("geo", None)
            if not loc.get("postalCode"):
                loc.pop("postalCode", None)
        if out:
            return {"status": "available", "locations": out}
        return {"status": "not_available", "locations": [], "message": "No registered address is listed."}

    def website_section(self, identity: dict[str, Any], description: dict[str, Any] | None) -> dict[str, Any]:
        mod = self.modules.get("website") or {}
        state = mod.get("state")
        if not self.researched and not self.website:
            return {"status": "pending", "message": PENDING, "pages": [], "social": [], "signals": []}
        w = self.website
        if not w.get("verified"):
            msg = mod.get("note") or "No official website verified in the searched permitted sources."
            status = {"blocked": "blocked", "ambiguous": "ambiguous", "failed": "not_available"}.get(state or "", "not_available")
            if status == "blocked":
                msg = "Source access blocked. " + msg
            if status == "ambiguous":
                msg = "A website was found, but it could not be verified as belonging to this exact company. " + (mod.get("note") or "")
            out = {"status": status, "message": msg.strip(), "pages": [], "social": [], "signals": [], "searchedSourceIds": ["brreg"]}
            if w.get("domain"):
                out["domain"] = w["domain"]
                out["url"] = w.get("url")
            if identity.get("website"):
                out["verification"] = identity["website"]
            return out
        audit = w.get("audit") or {}
        signal_text = {
            "org_number_on_site": "organisation number shown on the site", "norid_holder_match": "domain registered to this organisation number (Norid)",
            "registry_listed_website": "listed as the website in Enhetsregisteret", "legal_name_on_site": "legal name shown on the site",
            "registered_email_on_site": "registered e-mail address shown on the site", "registered_address_on_site": "registered address shown on the site",
            "registered_phone_on_site": "registered phone number shown on the site", "registered_email_domain": "registered e-mail uses this domain",
        }
        reasons = [signal_text[s] for s in audit.get("signals") or [] if s in signal_text]
        site_claim = self.first("official_website")
        verification = self.fact("website.verification", "Website ownership", site_claim, value=f"Verified — {', '.join(reasons[:3])}") if site_claim else None
        found = {p["kind"]: p for p in w.get("pages") or [] if p.get("status") == "ok"}
        pages = [{"kind": k, "title": t, "found": k in found, **({"url": found[k]["url"]} if k in found else {})} for k, t in PAGE_TITLES.items()]
        social = []
        for field, claims in self.by_field.items():
            if not field.startswith("social_profile_"):
                continue
            network = field.removeprefix("social_profile_")
            if network not in NETWORKS:
                continue
            for c in claims:
                handle = (c.get("attributes") or {}).get("handle")
                social.append({"network": network, "url": c["value"], **({"handle": handle} if handle else {}),
                               "fact": self.fact(f"website.social.{network}", network, c, value=handle or c["value"])})
        langs = {"nb": "Norwegian", "no": "Norwegian", "nn": "Norwegian", "en": "English", "sv": "Swedish", "da": "Danish", "de": "German"}
        lang_names = sorted({langs.get(lang, lang) for lang in w.get("languages") or [] if lang})
        signals = [
            {"label": "Careers page", "value": "Found" if "careers" in found else "Not found"},
            {"label": "Newsroom", "value": "Found" if "news" in found else "Not found"},
            {"label": "HTTPS", "value": "Yes" if w.get("https") else "No"},
        ]
        if lang_names:
            signals.insert(2, {"label": "Languages", "value": ", ".join(lang_names)})
        email = self.first("contact_email")
        if email:
            signals.append({"label": "Contact e-mail", "value": email["value"], "fact": self.fact("website.email", "Contact e-mail", email)})
        out = {"status": "available", "domain": w.get("domain"), "url": w.get("url"), "pages": pages, "social": social, "signals": signals,
               "searchedSourceIds": [f"web-{self.org}"]}
        if verification:
            out["verification"] = verification
        if description:
            out["description"] = description
        return out

    def hiring(self) -> dict[str, Any]:
        jobs_rec = self.r.get("jobs") or {}
        mod = self.modules.get("jobs") or {}
        if not self.researched and not jobs_rec.get("items"):
            return {"status": "pending", "message": PENDING, "totalCurrent": None, "locations": [], "categories": [], "jobs": [], "history": []}
        job_claims = {(c.get("key_suffix") or ""): c for c in self.by_field.get("job_posting") or []}
        jobs = []
        for item in jobs_rec.get("items") or []:
            claim = job_claims.get(item["id"])
            evidence = self.evidence_for(claim) if claim else []
            src = evidence[0]["sourceId"] if evidence else (f"web-{self.org}" if self.domain else "jobs")
            job = {"id": f"{self.org}-job-{item['id']}", "title": item["title"], "sourceId": src, "url": item.get("url"), "state": item.get("state") or "current",
                   "evidence": evidence}
            for k_src, k_dst in (("department", "department"), ("location", "location"), ("posted_at", "postedAt")):
                if item.get(k_src):
                    job[k_dst] = item[k_src]
            jobs.append(job)
        count_claim = self.first("open_positions_count")
        current = [j for j in jobs if j["state"] == "current"]
        if count_claim is not None:
            total = int(count_claim["value"])
            loc_counts = Counter(j.get("location") or "Unspecified" for j in current)
            cat_counts = Counter(j.get("department") or "Other" for j in current)
            return {"status": "available", "totalCurrent": total, "locations": [{"name": n, "count": c} for n, c in loc_counts.most_common()],
                    "categories": [{"name": n, "count": c} for n, c in cat_counts.most_common()], "jobs": jobs, "history": [],
                    "verifiedAt": self.researched_at, "searchedSourceIds": sorted({j["sourceId"] for j in jobs}) or [f"web-{self.org}"],
                    **({"message": "No current verified job openings were found in the searched sources."} if total == 0 else {})}
        state = mod.get("state")
        status = {"blocked": "blocked", "ambiguous": "ambiguous"}.get(state or "", "not_available")
        return {"status": status, "message": jobs_rec.get("note") or mod.get("note") or "No current verified job openings were found in the searched sources.",
                "totalCurrent": None, "locations": [], "categories": [], "jobs": jobs, "history": [], "searchedSourceIds": [f"web-{self.org}"] if self.domain else []}

    def activity(self) -> dict[str, Any]:
        events = []

        def add(date: str | None, typ: str, title: str, claim: dict[str, Any], major: bool, description: str | None = None) -> None:
            if not date or not re.match(r"^\d{4}-\d{2}-\d{2}$", date[:10]):
                return
            evidence = self.evidence_for(claim)
            ev = {"id": f"{self.org}-ev{len(events)}", "date": date[:10], "type": typ, "title": title, "significance": "major" if major else "minor",
                  "sourceIds": sorted({e["sourceId"] for e in evidence}), "evidence": evidence}
            if description:
                ev["description"] = description
            events.append(ev)

        for c in self.by_field.get("news_item") or []:
            title = str(c["value"])
            low = title.casefold()
            typ, major = "announcement", False
            if re.search(r"oppkjøp|kjøper|acquir|fusjon|merger", low):
                typ, major = "acquisition", True
            elif re.search(r"nytt kontor|new office|åpner|opens|ny avdeling|etablerer", low):
                typ, major = "location", True
            elif re.search(r"kontrakt|contract|avtale med|agreement|tildelt|awarded", low):
                typ, major = "contract", True
            elif re.search(r"ny daglig leder|new ceo|ansetter .* som|appoint", low):
                typ, major = "leadership", True
            add(c.get("as_of"), typ, title, c, major)
        reg = self.first("registration_date")
        if reg:
            add(reg["value"], "registration", "Registered in Enhetsregisteret", reg, True)
        founded = self.first("founded_date")
        if founded and (not reg or founded["value"] != reg["value"]):
            add(founded["value"], "registration", "Company founded", founded, True)
        parent = self.first("parent_company")
        if parent and parent.get("effective_from"):
            add(parent["effective_from"], "acquisition", f"Became part of the {parent['value']} group", parent, True,
                description=(parent.get("attributes") or {}).get("share") and f"Ownership basis: {(parent.get('attributes') or {}).get('share')}")
        for c in self.by_field.get("subsidiary") or []:
            if c.get("effective_from"):
                add(c["effective_from"], "acquisition", f"Subsidiary registered: {c['value']}", c, False)
        for c in self.by_field.get("registered_establishment") or []:
            if c.get("effective_from"):
                add(c["effective_from"], "location", f"Establishment opened: {(c.get('attributes') or {}).get('name') or c['value']}", c, True)
        for c in self.by_field.get("former_name") or []:
            if c.get("effective_to"):
                add(c["effective_to"], "registration", f"Name changed from {c['value']}", c, True)
        events.sort(key=lambda e: e["date"], reverse=True)
        if events:
            return {"status": "available", "events": events[:60]}
        if not self.researched:
            return {"status": "pending", "message": PENDING, "events": []}
        return {"status": "not_available", "message": "No dated public events were found in the searched sources.", "events": []}

    def changes_section(self) -> dict[str, Any]:
        if not self.researched:
            return {"status": "pending", "message": PENDING, "changes": []}
        out = []
        for ch in self.changes:
            src = {"sourceId": "brreg"}
            ev = {"id": f"{ch['id']}-ev", "sourceId": self._source_for_change(ch), "url": ch.get("source_url"), "retrievedAt": ch.get("retrieved_at") or ch.get("detected_at"),
                  "excerpt": f"{ch.get('label')}: {ch.get('old_display') or '—'} → {ch.get('new_display') or '—'}"}
            src.update(ev)
            item = {"id": ch["id"], "detectedAt": ch.get("detected_at"), "kind": ch.get("kind") or "modified", "category": ch.get("category") or "event",
                    "label": ch.get("label") or ch["field"], "headline": ch.get("headline"), "material": bool(ch.get("material", True)),
                    "explainable": (ch.get("category") in ("financial", "employees", "hiring", "leadership", "status", "location")), "evidence": [ev]}
            if ch.get("old_display") is not None:
                item["previous"] = str(ch["old_display"])
            if ch.get("new_display") is not None:
                item["current"] = str(ch["new_display"])
            if ch.get("direction"):
                item["direction"] = ch["direction"]
            out.append(item)
        base = {"since": self.previous_at, "baselineLabel": "previous research"} if self.previous_at else {}
        if out:
            return {"status": "available", "changes": out, **base}
        if not self.previous_at:
            return {"status": "not_available", "changes": [], "message": "This is the first research of this company. Changes are detected from the next refresh onward."}
        return {"status": "not_available", "changes": [], "message": "No verified material changes were detected since the previous research.", **base}

    def _source_for_change(self, ch: dict[str, Any]) -> str:
        field = ch.get("field") or ""
        mod = {"registry": "registry_live", "financials": "financials", "financial_history": "financial_history", "roles": "roles", "locations": "locations"}.get(field.split(".")[0])
        if mod:
            return self.sources.for_evidence({"module": mod})
        return f"web-{self.org}" if self.domain else "brreg"

    def relationships(self, people: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for p in people["people"]:
            if p["roleGroup"] in ("executive", "board"):
                out.append({"id": f"{p['id']}-rel", "kind": "ceo" if p["role"] == "CEO" else "board", "label": p["role"],
                            "entity": {"type": "person", "name": p["name"]}, "evidence": p["fact"]["evidence"][:1]})
        for field, kind, label in (("parent_company", "parent", "Parent company"), ("ultimate_parent_company", "related", "Ultimate parent"),
                                   ("subsidiary", "subsidiary", "Subsidiary")):
            for i, c in enumerate(self.by_field.get(field) or []):
                org = (c.get("attributes") or {}).get("organisation_number")
                ent = {"type": "organization", "name": c["value"]}
                if org:
                    ent["orgNumber"] = org
                out.append({"id": f"{self.org}-{field}-{i}", "kind": kind, "label": label, "entity": ent, "evidence": self.evidence_for(c)[:1]})
        return out

    def key_metrics(self, financials: dict[str, Any], identity: dict[str, Any], locations: dict[str, Any], hiring: dict[str, Any]) -> list[dict[str, Any]]:
        km = []
        for key in ("revenue", "operating_result", "annual_result"):
            s = next((x for x in financials["series"] if x["key"] == key), None)
            if s and s["points"]:
                km.append(s["points"][-1]["fact"])
        emp = self.first("registered_employees")
        km.append(self.fact("overview.employees", "Employees", emp, unit="people", display=format_int(emp["value"]) if emp else None, absent="registered_employees",
                            note=None if emp else "The register does not report an employee count (missing is not zero)."))
        if identity.get("founded"):
            km.append(identity["founded"])
        est = self.first("registered_establishment_count")
        if est is not None:
            km.append(self.fact("overview.locations", "Registered establishments", est, unit="sites"))
        if hiring["totalCurrent"] is not None:
            km.append(self.fact("overview.openPositions", "Open positions", self.first("open_positions_count"), unit="roles"))
        elif self.researched:
            km.append(self.fact("overview.openPositions", "Open positions", None, absent="open_positions_count", note=hiring.get("message")))
        return km

    def coverage(self, fin, people, locations, website, hiring, activity) -> dict[str, Any]:  # noqa: ANN001
        def area(name: str, status: str, note: str | None = None) -> dict[str, Any]:
            out = {"area": name, "status": status, "factCount": 0}
            if note:
                out["note"] = note
            return out

        fin_status = "complete" if fin["series"] and len(fin["series"]) >= 3 and len(fin["series"][0]["points"]) >= 2 else "partial" if fin["series"] else (
            "blocked" if fin["status"] == "blocked" else "unavailable")
        areas = [
            area("company_record", "complete" if self.first("legal_name") else "unavailable"),
            area("financials", fin_status, None if fin["series"] else fin.get("message")),
            area("people_locations", "complete" if people["people"] and locations["locations"] else "partial" if (people["people"] or locations["locations"]) else
                 ("pending" if people["status"] == "pending" else "unavailable")),
            area("website", {"available": "complete", "blocked": "blocked", "pending": "pending"}.get(website["status"], "unavailable"),
                 None if website["status"] == "available" else ("Not researched yet" if website["status"] == "pending" else website.get("message"))),
        ]
        if hiring["status"] == "pending":
            areas.append(area("hiring_activity", "pending", "Not researched yet"))
        else:
            has_h = hiring["totalCurrent"] is not None
            has_a = bool(activity["events"])
            areas.append(area("hiring_activity", "complete" if has_h and has_a else "partial" if has_h or has_a else
                              ("blocked" if hiring["status"] == "blocked" else "unavailable"), None if has_h else "Hiring data unavailable"))
        sections = {"company_record": ("identity", "overview"), "financials": ("financials",), "people_locations": ("people", "locations"), "website": ("website",),
                    "hiring_activity": ("hiring", "activity")}
        for a in areas:
            a["factCount"] = sum(1 for f, sec in self.facts if sec in sections[a["area"]] and f["status"] == "verified")
        return {"complete": sum(1 for a in areas if a["status"] == "complete"), "total": 5, "areas": areas}

    def source_usage(self, hiring, activity, changes) -> list[dict[str, Any]]:  # noqa: ANN001
        usage: dict[str, dict[str, Any]] = {}

        def note(ev: dict[str, Any], section: str, count: bool = True) -> None:
            src = self.sources.sources.get(ev["sourceId"])
            if not src:
                return
            u = usage.setdefault(src["id"], {"source": src, "factCount": 0, "lastRetrievedAt": ev.get("retrievedAt") or "", "sections": [], "evidenceIds": []})
            if ev["id"] not in u["evidenceIds"]:
                u["evidenceIds"].append(ev["id"])
                if count:
                    u["factCount"] += 1
            if (ev.get("retrievedAt") or "") > u["lastRetrievedAt"]:
                u["lastRetrievedAt"] = ev["retrievedAt"]
            if section not in u["sections"]:
                u["sections"].append(section)

        for f, sec in self.facts:
            for ev in f["evidence"]:
                note(ev, sec)
        for j in hiring["jobs"]:
            for ev in j["evidence"]:
                note(ev, "hiring")
        for e in activity["events"]:
            for ev in e["evidence"]:
                note(ev, "activity")
        rank = {"primary": 0, "secondary": 1, "discovery": 2}
        return sorted(usage.values(), key=lambda u: (rank.get(u["source"]["tier"], 3), -u["factCount"]))

    def summary(self) -> dict[str, Any] | None:
        s = self.r.get("summary") or {}
        if not s.get("text"):
            return None
        source_ids = []
        for eid in s.get("evidence_ids") or []:
            ev = self.ev_by_id.get(eid)
            if ev:
                sid = self.sources.for_evidence(ev)
                if sid not in source_ids:
                    source_ids.append(sid)
        return {"text": s["text"], "sourceIds": source_ids[:6], "evidenceIds": [e for e in s.get("evidence_ids") or [] if e in self.ev_by_id][:10],
                "generatedAt": s.get("generated_at") or self.researched_at}

    def knowns(self, identity, people, financials, hiring, website) -> list[dict[str, Any]]:  # noqa: ANN001
        k = [{"id": "k-identity", "label": "Identity", "text": f"Matched to org. no. {self.org} in Enhetsregisteret.", "status": "verified", "factId": identity["legalName"]["id"]}]
        ceo = next((p for p in people["people"] if p["role"] == "CEO"), None)
        k.append({"id": "k-ceo", "label": "CEO", "text": f"{ceo['name']}, registered as daglig leder." , "status": "verified", "factId": ceo["fact"]["id"]} if ceo else
                 {"id": "k-ceo", "label": "CEO", "text": "Not registered in Enhetsregisteret." if (self.modules.get("roles") or {}).get("state") == "available" else
                  "Not verified in searched permitted sources.", "status": "unknown"})
        rev = next((s for s in financials["series"] if s["key"] == "revenue"), None)
        if rev and rev["points"]:
            last = rev["points"][-1]
            k.append({"id": "k-rev", "label": "Latest revenue", "text": f"{last['period']} figure from filed annual accounts.",
                      "status": "conflict" if last["fact"].get("conflict") else "verified", "factId": last["fact"]["id"]})
        else:
            k.append({"id": "k-rev", "label": "Revenue", "text": financials.get("message") or "No filed annual accounts found.", "status": "unknown"})
        if hiring["totalCurrent"] is not None:
            k.append({"id": "k-hiring", "label": "Current hiring", "text": f"{hiring['totalCurrent']} verified opening{'' if hiring['totalCurrent'] == 1 else 's'} on company-owned pages.",
                      "status": "verified"})
        else:
            k.append({"id": "k-hiring", "label": "Current hiring", "text": "Not researched yet." if hiring["status"] == "pending" else
                      "No current verified openings found in searched sources.", "status": "unknown"})
        if website["status"] == "available":
            k.append({"id": "k-web", "label": "Official website", "text": f"{website.get('domain')}, ownership verified.", "status": "verified"})
        elif website["status"] == "blocked":
            k.append({"id": "k-web", "label": "Website content", "text": "Source access blocked.", "status": "blocked"})
        else:
            k.append({"id": "k-web", "label": "Official website", "text": "Not researched yet." if website["status"] == "pending" else
                      "Not verified in searched permitted sources.", "status": "unknown"})
        k.append({"id": "k-hq", "label": "Headquarters", "text": "Only the registered business address is known; an operating headquarters is not verified.", "status": "unknown"})
        return k


def build_profile(record: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return Builder(record, **kwargs).build()


# ---------------------------------------------------------- registry rows --
def summary_from_entity(row: dict[str, Any], *, researched_at: str | None = None) -> dict[str, Any]:
    """CompanySummary from a raw Enhetsregisteret entity (search results) — registry facts only."""
    from ..identity.model import identity_from_entity

    org = str(row.get("organisasjonsnummer") or "")
    ident = identity_from_entity(org, row, source_url="", retrieved_at=None, content_sha256=None)
    status = STATUS_MAP.get(ident.status or "", "other")
    areas = [{"area": "company_record", "status": "complete", "factCount": 0}] + [
        {"area": a, "status": "pending", "factCount": 0, "note": "Not researched yet"} for a in ("financials", "people_locations", "website", "hiring_activity")]
    out = {
        "orgNumber": org, "legalName": ident.legal_name or org, "municipality": title_case_no(ident.municipality) or None, "county": ident.county, "country": "Norway",
        "industry": {"code": ident.industry_code, "description": ident.industry_label or ""} if ident.industry_code else None, "status": status,
        "statusLabel": ident.status_label, "employees": ident.employees, "revenue": None, "openPositions": None,
        "coverage": {"complete": 1, "total": 5, "areas": areas}, "lastResearchedAt": researched_at, "researchState": "researched" if researched_at else "not_researched",
        "website": None, "geo": None, "tags": [],
    }
    return {k: v for k, v in out.items() if v is not None or k in ("employees", "revenue", "openPositions", "lastResearchedAt", "website", "geo")}


def summary_from_record(record: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return build_profile(record, **kwargs)["company"]


def now() -> str:
    return now_iso()
