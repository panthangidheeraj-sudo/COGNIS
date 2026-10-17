"""Regulatory notices, public decisions and official announcements (domain E: innovation, patents and regulation).

What is covered, and what is not
- **Official regulators and law-makers** (Finanstilsynet, Konkurransetilsynet, Datatilsynet, Regjeringen, EFTA Surveillance Authority, EUR-Lex …; the
  allowlist is ``REGULATORY_DOMAINS``). One targeted web search (Tavily, free allowance only) asks for pages naming the company; the hits are candidates,
  never evidence. Each candidate on the allowlist is fetched (robots.txt, SSRF policy and rate limits apply) and must tie itself to *this exact
  organisation*: its organisation number is on the page, or it names the exact registered name (a longer company name that merely starts with it, or a
  page that states another organisation's number, is rejected). A search engine's snippet is never used.
- **Patents, trademarks and designs** are *not* collected. Patentstyret's data API needs a registered subscription key, and its public search is a
  script-driven application whose data endpoints are undocumented; neither is a source COGNIS may use under its free/anonymous rule. The category is
  therefore reported as ``unavailable`` — never as "no patents".

Every accepted item states what kind of document it is *and how far it has got*: a proposal or consultation is not an enacted rule, a notice of intended
decision or an investigation is an allegation, not a final decision, and an application is not a granted right. Nothing is inferred when the page does not say.
A failed search, an unconfigured key or an exhausted free allowance is a recorded limitation, never "no results".
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..core.util import clean_ws, date_only, fold, now_iso, truncate
from ..evidence.models import ModuleResult
from ..extraction.html import PageDoc
from ..identity.employer import org_numbers_in
from ..identity.model import CanonicalIdentity
from ..identity.normalization import is_generic_name, name_in_text, normalize_name
from ..security.urls import host_of
from . import search
from .base import ConnectorContext, not_run
from .job_discovery import _can_spend, short_name
from .news_discovery import allowed_domains, continues_into_longer_name, outlet_of
from .website import fetch_page

MODULE = "regulatory"
SOURCE_ID = "regulatory_official"
SOURCE_NAME = "Official regulators and public notices (found by search)"
SOURCE_CLASS = "government_regulator"
EXCERPT_CHARS = 300
MAX_ACCEPTED = 8

IP_UNAVAILABLE_NOTE = (
    "Not checked: Patentstyret's data API needs a registered subscription key and its public search is a script-driven application without a documented "
    "anonymous data endpoint, so COGNIS does not read it. This says nothing about whether the company holds patents, trademarks or designs."
)
IP_CATEGORIES = ("patents", "trademarks", "designs")


def ip_status() -> dict[str, dict[str, str]]:
    """Patents, trademarks and designs: always ``unavailable`` (see module docstring), with the reason."""
    return {k: {"status": "unavailable", "note": IP_UNAVAILABLE_NOTE} for k in IP_CATEGORIES}


# ----------------------------------------------------------------------------- classification --
def _rx(*alts: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")", re.I)


# Order matters: an allegation ("varsel om vedtak") must win over the word "vedtak" it contains, and a sanction over "vedtatt".
ALLEGATION = _rx(r"varsel om (?:vedtak|overtredelsesgebyr|pålegg)", r"statement of objections", r"preliminary (?:finding|assessment|view)", r"investigat\w*", r"etterforsk\w*",
                 r"undersøk\w*", r"suspect\w*", r"mistenk\w*", r"alleg\w*", r"anmeld\w*", r"opens? (?:a )?(?:case|probe)", r"åpner (?:sak|tilsyn)", r"tilsynssak", r"intends? to (?:fine|impose)")
SANCTION = _rx(r"overtredelsesgebyr", r"gebyr", r"ilagt", r"ilegg\w*", r"fined?\b", r"fines\b", r"imposed", r"pålegg\w*", r"tvangsmulkt")
PROPOSAL = _rx(r"høring\w*", r"forslag\w*", r"utkast", r"proposal\w*", r"proposed", r"consultation", r"draft\b", r"white paper", r"stortingsmelding", r"prop\.? \d+ ?[ls]")
ENACTED = _rx(r"vedtatt", r"adopted", r"entered into force", r"trer i kraft", r"i kraft", r"enacted", r"fastsatt")
REGWORD = _rx(r"forskrift\w*", r"lov(?:en)?\b", r"regulation\w*", r"directive\w*", r"direktiv\w*", r"regelverk", r"rule[s]?\b", r"act\b", r"bestemmelse\w*")
FINAL = _rx(r"vedtak\b", r"vedtok", r"decision", r"decided", r"avgjørelse", r"ruling", r"approved", r"godkjent", r"konsesjon", r"licen[cs]e granted", r"tillatelse")
NOTICE = _rx(r"melding", r"notice", r"announce\w*", r"pressemelding", r"press release", r"kunngjør\w*", r"informasjon")


def classify_stage(text: str) -> tuple[str, str]:
    """(kind, stage) from the document's own wording. ``unclear`` when it does not say or says two things — never guessed upwards to a final decision."""
    t = clean_ws(text or "")
    if ALLEGATION.search(t):
        return "enforcement", "allegation_or_investigation"
    if SANCTION.search(t):
        return "decision", "final_decision"
    proposal, enacted = bool(PROPOSAL.search(t)), bool(ENACTED.search(t) and REGWORD.search(t))
    if proposal and enacted:
        return "regulation", "unclear"
    if proposal:
        return "regulation", "proposal"
    if enacted:
        return "regulation", "enacted"
    if FINAL.search(t):
        return "decision", "final_decision"
    if NOTICE.search(t):
        return "announcement", "announcement"
    return "announcement", "unclear"


STAGE_LABEL = {
    "allegation_or_investigation": "Allegation or investigation — not a final decision",
    "proposal": "Proposal or consultation — not an enacted rule",
    "enacted": "Enacted rule",
    "final_decision": "Decision",
    "announcement": "Official announcement",
    "unclear": "Official page (the kind of document is not stated)",
}


# ------------------------------------------------------------------------------------ identity --
def identity_basis(doc: PageDoc, identity: CanonicalIdentity) -> tuple[str | None, str | None]:
    """How the page is tied to this exact organisation: (basis, None) or (None, reason)."""
    numbers = org_numbers_in([doc.text])
    if identity.org_number in numbers:
        return "organisation_number_on_page", None
    if numbers:
        return None, "the page states a different organisation number"
    legal = re.sub(r"\ba\s*/\s*s\b", "AS", identity.legal_name or "", flags=re.I)
    if is_generic_name(legal) or len(normalize_name(legal)) < 5:
        return None, "the registered name is too generic to tie a page to this organisation without an organisation number"
    surface = " ".join([doc.title, *doc.headings[:6], doc.text[:20000]])
    if name_in_text(legal, surface) and not continues_into_longer_name(surface, legal):
        return "exact_legal_name_on_page", None
    return None, "the page does not name this exact organisation (a similar name or a shared word is not enough)"


def _page_date(doc: PageDoc) -> str | None:
    raw = doc.og.get("published_time") or doc.og.get("updated_time") or ""
    day = date_only(raw)
    if not day:
        day = next((date_only(t.datetime[:10]) for t in doc.times if t.datetime), None)
    return day


def _summary(doc: PageDoc, legal: str) -> str:
    """A short verbatim passage: the first sentence that names the company, else the first substantial paragraph."""
    for para in doc.paragraphs[:80]:
        if name_in_text(legal, para) and len(para) >= 40:
            return truncate(para, EXCERPT_CHARS)
    return truncate(next((p for p in doc.paragraphs if len(p) >= 60), doc.description or ""), EXCERPT_CHARS)


def item_id(url: str, title: str) -> str:
    return "reg-" + hashlib.sha1(f"{url.split('#')[0].rstrip('/').lower()}|{fold(title)[:80]}".encode()).hexdigest()[:12]


@dataclass
class RegulatoryResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    modules: list[ModuleResult] = field(default_factory=list)  # the search call itself
    module: ModuleResult | None = None
    searched: bool = False
    searches_used: int = 0

    def summary(self) -> dict[str, Any]:
        """What the record stores under ``record["regulatory"]``."""
        mod = self.module
        return {"state": mod.state if mod is not None else "not_applicable", "note": mod.note if mod is not None else None, "items": self.items,
                "candidates": self.candidates[:25], "ip": ip_status(), "checked_at": now_iso(), "searches_used": self.searches_used}


def _skipped(note: str, state: str = "not_applicable") -> RegulatoryResult:
    return RegulatoryResult(module=not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state=state, note=note, tier="C"))


async def discover_regulatory(ctx: ConnectorContext, identity: CanonicalIdentity, *, today: date | None = None, max_searches: int | None = None,
                              max_pages: int | None = None) -> RegulatoryResult:
    s = ctx.settings
    today = today or date.today()
    if not s.enable_regulatory_discovery:
        return _skipped("Regulatory-notice search is switched off by configuration. Not checked.")
    if not s.search_enabled:
        return _skipped("Not checked: web search is not configured (TAVILY_API_KEY missing), so official regulator pages could not be searched.")
    allowed = allowed_domains(s.regulatory_domains)
    if not allowed:
        return _skipped("No official regulator domains are configured. Not checked.")
    if max_searches is not None and max_searches <= 0:
        return _skipped("Not checked: this request may not use web search.")
    if is_generic_name(identity.legal_name) and not identity.org_number:
        return _skipped("The registered name is too generic to search regulator pages without mixing up companies. Not checked.")
    if not _can_spend(ctx.budget):
        return _skipped("Not run: the research budget for optional lookups was used up.", state="blocked")

    legal = identity.legal_name or ""
    spaced = f"{identity.org_number[:3]} {identity.org_number[3:6]} {identity.org_number[6:]}"
    query = f'"{short_name(legal)}" OR "{spaced}" vedtak tilsyn overtredelsesgebyr høring forskrift patent konsesjon decision regulation'
    mod, hits = await search.web_search(ctx, query, count=10, include_domains=allowed)
    out = RegulatoryResult(modules=[mod], searched=True, searches_used=1)
    if mod.state in ("blocked", "failed"):
        tripped = bool(getattr(ctx.http, "tripped", {}).get("search"))  # the key was refused or the free allowance is used up
        out.module = not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state="blocked" if tripped else mod.state, tier="C",
                             note=f"Web search was unavailable ({mod.note or mod.state}), so official regulator pages could not be checked. This is not evidence that there are no regulatory matters.")
        return out

    limit = max_pages if max_pages is not None else s.regulatory_max_pages
    fetched = 0
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    for hit in hits:
        cand: dict[str, Any] = {"url": hit.url, "title": hit.title[:140], "rank": hit.rank}
        site = outlet_of(hit.url, allowed)
        if site is None:
            out.candidates.append({**cand, "status": "ignored", "reason": "not an official regulator on the allowlist; page not fetched"})
            continue
        key = hit.url.split("#")[0].rstrip("/").lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        if len(out.items) >= MAX_ACCEPTED:
            out.candidates.append({**cand, "status": "not_checked", "reason": "enough items were already verified"})
            continue
        if fetched >= limit or not _can_spend(ctx.budget):
            out.candidates.append({**cand, "status": "not_checked", "reason": "page limit or budget reached"})
            continue
        res, doc = await fetch_page(ctx, hit.url, connector="regulatory", optional=True)
        fetched += 1
        if doc is None:
            reason = {"robots_disallowed": "robots.txt does not allow fetching this page (respected)", "blocked": "the site refused access (not worked around)",
                      "not_found": "the page no longer exists", "gone": "the page no longer exists"}.get(res.classification, f"the page could not be read ({res.classification})")
            out.candidates.append({**cand, "status": "blocked" if res.classification in ("robots_disallowed", "blocked") else "unreadable", "reason": reason})
            continue
        basis, why = identity_basis(doc, identity)
        if basis is None:
            out.candidates.append({**cand, "status": "unverified", "reason": why})
            continue
        title = clean_ws(doc.og.get("title") or (doc.headings[0] if doc.headings else "") or doc.title)[:220]
        if not title:
            out.candidates.append({**cand, "status": "unverified", "reason": "no title could be read from the page"})
            continue
        day = _page_date(doc)
        if day and day > today.isoformat():
            out.candidates.append({**cand, "status": "rejected", "reason": "the page is dated in the future"})
            continue
        kind, stage = classify_stage(f"{title}. {doc.description}. {' '.join(doc.paragraphs[:6])}")
        ident = item_id(doc.final_url, title)
        if ident in seen_ids:
            continue
        seen_ids.add(ident)
        out.items.append({
            "id": ident, "organisation_number": identity.org_number, "kind": kind, "stage": stage, "stage_label": STAGE_LABEL[stage], "title": title,
            "summary": _summary(doc, legal), "url": doc.final_url, "published": day, "retrieved_at": doc.retrieved_at or now_iso(), "source_name": host_of(doc.final_url),
            "source_class": SOURCE_CLASS, "source_type_label": "Government / regulator", "identity_basis": basis, "identity_score": 1.0 if basis == "organisation_number_on_page" else 0.9,
            "verification": "verified_page_read", "uncertainty": None if day else "The page states no publication date.",
        })
        out.candidates.append({**cand, "title": title[:140], "date": day, "status": "accepted", "reason": f"tied to this organisation by {basis.replace('_', ' ')}"})
    accepted = len(out.items)
    problems = len([c for c in out.candidates if c["status"] in ("unverified", "rejected", "unreadable", "blocked")])
    if accepted:
        state, note = "available", f"Search suggested {len(hits)} page(s); {accepted} official page(s) verified as naming this company" + (f", {problems} could not be used" if problems else "") + "."
    else:
        state = "not_available"
        note = ("No public results found in the checked sources: " + (f"search suggested {len(hits)} page(s) but none could be tied to this exact organisation." if hits
                                                                   else "no official regulator page named this company.") + " This does not mean there are no regulatory matters.")
    out.module = ModuleResult(module=MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state=state, note=note, tier="C", retrieved_at=now_iso(),
                              value={"query": query, "hits": len(hits), "fetched": fetched, "accepted": accepted, "candidates": out.candidates[:20]})
    return out
