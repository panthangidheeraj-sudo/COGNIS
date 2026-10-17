"""Chat's targeted lookup: a small, question-focused check of current sources — not the deep-research pipeline.

When the saved evidence cannot answer a chat question (or is too old, or the user asks to check again), Chat used to start the full deep-research orchestrator:
every connector in turn, within a 45-second limit, streaming each connector call to the screen. Most of that work had nothing to do with the question, and when the
limit was reached the answer fell back to the saved evidence anyway. This module replaces that with one bounded lookup for the specific thing asked:

1. **Official source first, when it applies.** A question about financial results reads the latest filed annual accounts in Regnskapsregisteret (one request),
   through the same extraction and publication gate research uses. Amounts keep the currency and the reporting period their own filing states.
2. **One targeted web search** (Tavily, free allowance only; at most ``chat_max_searches`` calls, a second one only when the first found nothing usable),
   restricted to permitted domains: the company's own website (verified or register-listed), the configured reputable news outlets, and — for a regulatory
   question — the official regulator allowlist. Search results are candidates, never evidence; their snippets are never shown or used.
3. **At most ``chat_lookup_max_pages`` pages are fetched**, in parallel, by COGNIS itself (robots.txt, the SSRF policy and rate limits apply). Each page must
   tie itself to this exact organisation (its own website, its organisation number, or its exact registered name; a page stating another organisation's number
   is rejected). From each page only the passages relevant to the question are kept, with the page's own publication date when it states one.

Everything is bounded: a wall-clock limit for the whole lookup (``chat_lookup_timeout_seconds``), a per-page limit, no retries of a page, and a small result cache
so asking the same question twice does not spend the free search allowance twice. A failure is reported as what it was — "not configured", "unavailable",
"did not finish in time", or "checked, nothing usable found" — never as a successful lookup. The extracts become numbered evidence items that the configured
model (Groq) may write from; the chat's evidence validator then checks every figure, citation and URL exactly as before.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..connectors import brreg, search
from ..connectors.base import ConnectorContext
from ..connectors.job_discovery import short_name
from ..connectors.news_discovery import allowed_domains, continues_into_longer_name, outlet_of
from ..connectors.regulatory import _page_date, classify_stage
from ..connectors.website import HTML_ACCEPT
from ..core.util import clean_ws, date_only, fold, format_money, now_iso, truncate
from ..evidence.gate import publish
from ..extraction import registry_facts as rf
from ..extraction.html import PageDoc, parse_html
from ..identity.employer import org_numbers_in
from ..identity.model import CanonicalIdentity
from ..identity.normalization import name_in_text
from ..logging_setup import get_logger
from ..runtime.budgets import CompanyBudget
from ..security.urls import host_of, normalize_website, registrable_domain
from .chat_intent import event_status

log = get_logger("chat.lookup")

Emit = Any  # callable(stage, label, **extra)

# words that say nothing about WHAT is asked (they are not search terms)
_STOP = set("""
a an the and or but of to in on at for from by with about into over than then this that these those it its it's their they them is are was were be been being has have had do does did
can could would should will shall may might must what which who whom whose when where why how much many any some all each every more most other such no not only own same so too very
please tell me show give list find summarise summarize summary describe explain include including identify clearly distinguish compare between whether also and/or etc
company company's firm business ab as asa ltd inc plc group latest recent current currently new newest last year years source sources link links cannot verify verified
information info details data question answer research check look up recently happened happen happening going today now
hva hvem hvor når hvordan hvilke hvilken er var har og eller i på av til for med om fra det den de som siste nyeste
""".split())

# what each kind of question is about, as search words (English and Norwegian)
DOMAIN_TERMS: dict[str, list[str]] = {
    "financials": ["annual report", "results", "revenue", "net income", "operating income", "årsrapport", "resultat"],
    "news": ["news", "announcement", "press release"],
    "regulatory": ["decision", "regulator", "vedtak", "tilsyn"],
    "hiring": ["careers", "jobs", "vacancies", "stillinger"],
    "contracts": ["contract", "awarded", "agreement", "kontrakt"],
    "structure": ["board", "management", "group structure"],
}
# passage scoring: words that make a paragraph relevant to that kind of question
DOMAIN_CUES: dict[str, list[str]] = {
    "financials": ["revenue", "revenues", "income", "net income", "result", "profit", "loss", "ebit", "operating", "earnings", "quarter", "full year", "full-year",
                   "annual", "fiscal", "usd", "nok", "eur", "billion", "million", "driftsinntekter", "årsresultat", "resultat", "omsetning", "consolidated", "group"],
    "news": ["announce", "announced", "agreement", "contract", "acquisition", "launch", "signed", "awarded", "kunngjør", "avtale"],
    "regulatory": ["decision", "fine", "investigation", "regulator", "vedtak", "gebyr", "tilsyn", "licence", "license"],
    "hiring": ["job", "position", "vacancy", "career", "stilling"],
    "contracts": ["contract", "award", "awarded", "tender", "kontrakt"],
}
BOILERPLATE = re.compile(r"(cookie|personvern|privacy|javascript|abonnement|subscribe|logg inn|log in|sign in|©|all rights reserved|newsletter)", re.I)
FIN_FIELDS = ("revenue", "operating_result", "profit_before_tax", "annual_result", "total_assets", "equity", "total_liabilities")


@dataclass
class Found:
    """One dated extract from a permitted source, ready to become a numbered evidence item."""
    kind: str  # fact | event | regulatory
    text: str
    title: str
    url: str
    published: str | None
    retrieved: str | None
    source_class: str  # official_register | company_disclosure | government_regulator | secondary_reporting
    period: str | None = None
    currency: str | None = None
    scope: str | None = None
    uncertainty: str | None = None
    status: str | None = None
    link_kind: str = "web_page"  # filing_document (a filed copy the register lists) | register_record (a register data record, not the filing) | web_page
    record_url: str | None = None  # where the figures were read, when that differs from ``url``


@dataclass
class Lookup:
    state: str  # used | no_results | unavailable | timeout | not_configured
    note: str
    found: list[Found] = field(default_factory=list)
    checked: list[dict[str, Any]] = field(default_factory=list)  # every source looked at, and what became of it (shown on request)
    searches: int = 0
    elapsed_ms: int = 0
    cached: bool = False

    def search_note(self) -> dict[str, Any]:
        """What the answer shows about this lookup. ``checked`` lists only sources that were really read (the register's records and the pages COGNIS fetched);
        search calls and results that were never opened are counted in ``web``, not listed as checked sources."""
        real = [{k: v for k, v in c.items() if k in ("name", "url", "state", "reason", "kind", "linkKind")} for c in self.checked if c.get("kind") != "search" and c.get("state") != "skipped"]
        calls = [c for c in self.checked if c.get("kind") == "search"]
        web = {"searches": self.searches, "results": sum(int(c.get("results") or 0) for c in calls), "notOpened": sum(1 for c in self.checked if c.get("state") == "skipped"),
               "state": calls[-1]["state"] if calls else "not_used", "note": calls[-1].get("reason") if calls else None}
        return {"state": self.state, "note": self.note, "checked": real[:12], "web": web, "lookup": {"searches": self.searches, "elapsedMs": self.elapsed_ms, "cached": self.cached}}


# ----------------------------------------------------------------------------------------- query --
def question_terms(question: str, legal_name: str, *, limit: int = 5) -> list[str]:
    """The distinctive words of the question (not instructions, not the company's own name), in order."""
    name_words = {w for w in re.findall(r"\w+", fold(legal_name or ""))}
    out: list[str] = []
    for w in re.findall(r"[^\W_][\w&-]*", question):
        f = fold(w).strip("-")
        if len(f) < 3 or f in _STOP or f in name_words or f.isdigit() and len(f) != 4:
            continue
        if f not in out:
            out.append(f)
    return out[:limit]


def build_query(question: str, legal_name: str, domains: list[str], years: list[int]) -> str:
    """'"Equinor" annual report results revenue net income 2025' — the company's name, what kind of thing is asked, and the question's own key words."""
    name = short_name(re.sub(r"\ba\s*/\s*s\b", "AS", legal_name or "", flags=re.I)).strip() or legal_name
    words: list[str] = []
    for d in domains:
        for t in DOMAIN_TERMS.get(d, [])[:4]:
            if t not in words:
                words.append(t)
    for t in question_terms(question, legal_name):
        if not any(t in w for w in words):
            words.append(t)
    words += [str(y) for y in years if str(y) not in words]
    return clean_ws(f'"{name}" ' + " ".join(words[:10]))[:380]


# ----------------------------------------------------------------------------------- passages --
def relevant_passages(doc: PageDoc, question: str, legal_name: str, domains: list[str], *, max_passages: int = 3, max_chars: int = 900) -> list[str]:
    """The page's own sentences that bear on the question, in page order (verbatim, trimmed). Nothing is summarised or rewritten here."""
    terms = set(question_terms(question, legal_name, limit=12))
    cues = {c for d in domains for c in DOMAIN_CUES.get(d, [])}
    wants_numbers = "financials" in domains
    paras = [clean_ws(p) for p in (doc.paragraphs or [])]
    if not paras and doc.text:
        paras = [clean_ws(x) for x in re.split(r"(?<=[.!?])\s+(?=[A-ZÆØÅ])", doc.text) if x.strip()]
    scored: list[tuple[int, int, str]] = []
    for i, p in enumerate(paras):
        if len(p) < 40 or BOILERPLATE.search(p[:160]):
            continue
        fp = fold(p)
        score = sum(2 for t in terms if t in fp) + sum(1 for c in cues if c in fp)
        if score and wants_numbers and re.search(r"\d[\d .,]*\s*(?:%|million|billion|mill|mrd|bn|[A-Z]{3})", p):
            score += 2  # a passage that states an amount is what a question about results needs
        if score > 0:
            scored.append((score, i, p))
    best = sorted(scored, key=lambda x: (-x[0], x[1]))[:max_passages]
    out, used = [], 0
    for _score, _i, p in sorted(best, key=lambda x: x[1]):
        piece = truncate(p, 360)
        if used + len(piece) > max_chars:
            break
        out.append(piece)
        used += len(piece)
    return out


def page_date(doc: PageDoc) -> str | None:
    """The publication date the page itself states (structured data, meta tags, <time>), or None. Never the search engine's guess."""
    for ld in doc.jsonld or []:
        raw = ld.get("datePublished") or ld.get("dateCreated") or ld.get("dateModified") if isinstance(ld, dict) else None
        day = date_only(str(raw)) if raw else None
        if day:
            return day
    return _page_date(doc)


def ties_to_company(doc: PageDoc, identity: CanonicalIdentity, own_domains: set[str]) -> tuple[str | None, str | None]:
    """(basis, None) when the page is about this exact organisation, else (None, reason). A similar name or a shared word is never enough."""
    numbers = org_numbers_in([doc.text[:40000]])
    if identity.org_number in numbers:
        return "organisation number on the page", None
    if numbers and doc.domain not in own_domains:
        return None, "the page states a different organisation number"
    if doc.domain in own_domains:
        return "the company's own website", None
    legal = re.sub(r"\ba\s*/\s*s\b", "AS", identity.legal_name or "", flags=re.I)
    pieces = [doc.title, *doc.headings[:8], *doc.paragraphs[:80]] or []
    if not doc.paragraphs:
        body = doc.text[:20000]
        body = body[len(doc.title):] if doc.title and body.startswith(doc.title) else body  # the page text starts with its <title>
        pieces += re.split(r"(?<=[.!?])\s+", body)
    # each sentence or heading on its own: "Equinor Energy AS" in one sentence is another company; a title word never runs into the name
    if any(name_in_text(legal, p) and not continues_into_longer_name(p, legal) for p in pieces if p):
        return "names the exact registered company name", None
    return None, "the page does not name this exact organisation"


# ------------------------------------------------------------------------------------- sources --
def own_domains(record: dict[str, Any], identity: CanonicalIdentity) -> set[str]:
    out: set[str] = set()
    site = record.get("website") or {}
    if site.get("verified") and site.get("domain"):
        out.add(registrable_domain(str(site["domain"])))
    if identity.website:  # the website the company itself registered in Enhetsregisteret
        url = normalize_website(identity.website)
        if url:
            out.add(registrable_domain(host_of(url)))
    return {d for d in out if d}


async def official_accounts(ctx: ConnectorContext, identity: CanonicalIdentity) -> tuple[list[Found], list[dict[str, Any]]]:
    """The latest filed annual accounts (Regnskapsregisteret), through the publication gate, and which filed copies the register lists. Two requests, in parallel.

    Standalone (SELSKAP) and consolidated (KONSERN) accounts are separate items, never merged, each with its own reporting period. Each item says where its figures were
    read (the register's data record — not a copy of the filing) and, only when the register itself lists one for that year, the direct link to the filed copy."""
    org = identity.org_number
    mod, hist = await asyncio.gather(brreg.fetch_financials(ctx, identity, optional=True), brreg.fetch_financial_history(ctx, identity, optional=True))
    record_url = mod.url or brreg.BRREG_ACCOUNTS.format(org=org)
    rows: list[dict[str, Any]] = [{"name": "Regnskapsregisteret — data record of the latest filed annual accounts", "url": record_url, "kind": "official", "linkKind": "register_record"}]
    copies = {str(p["year"]): p["url"] for p in ((hist.value or {}).get("pdfs") or [])} if hist.state == "available" else {}
    rows.append({"name": "Regnskapsregisteret — list of filed annual-account copies", "url": hist.url or brreg.BRREG_ACCOUNT_YEARS.format(org=org), "kind": "official", "linkKind": "register_record",
                 "state": "used" if copies else ("unavailable" if hist.state in ("failed", "blocked") else "nothing_found"),
                 "reason": (f"copies listed for {', '.join(sorted(copies))}" if copies else (hist.note or "no filed copies are listed"))})
    if mod.state != "available":
        why = mod.note or (mod.classification or mod.state or "").replace("_", " ")
        rows[0].update(state="unavailable" if mod.state in ("failed", "blocked") else "nothing_found", reason=why)
        return [], rows
    claims, _rej = publish(rf.financial_observations(mod), org)
    groups: dict[tuple[str, str], list[Any]] = {}
    for c in claims:
        base = c.field.removeprefix("consolidated_")
        if base in FIN_FIELDS and isinstance(c.value, (int, float)) and not c.conflict:
            obs = c.primary
            kind = str((obs.attributes or {}).get("account_type") or ("KONSERN" if c.field.startswith("consolidated_") else "SELSKAP")) if obs else ""
            groups.setdefault((c.period_label or c.reporting_period or "", kind.upper()), []).append(c)
    # per accounting scope, its latest period (and the one before it): standalone and consolidated never crowd each other out
    keep: list[tuple[str, str]] = []
    for scope_kind in ("KONSERN", "SELSKAP"):
        keep += sorted((k for k in groups if k[1] == scope_kind), key=lambda k: k[0], reverse=True)[:2]
    keep += [k for k in groups if k[1] not in ("KONSERN", "SELSKAP")][:1]
    found: list[Found] = []
    for period, kind in sorted(keep, key=lambda k: (k[0], k[1] == "KONSERN"), reverse=True)[:4]:
        cs = sorted(groups[(period, kind)], key=lambda c: FIN_FIELDS.index(c.field.removeprefix("consolidated_")))
        scope = SCOPE_OF.get(kind, kind.lower() or None)
        currency = next((c.currency for c in cs if c.currency), None)
        parts = [f"{c.label or c.field} {period}: {format_money(c.value, c.currency)} (value: {float(c.value):.0f})" for c in cs]
        span = cs[0].primary.claim_span if cs[0].primary else ""
        url, link_kind, title = filing_link(org, period, scope, copies, record_url, copies_known=hist.state in ("available", "not_available"))
        found.append(Found("fact", f"[{scope or 'accounting scope not stated'} accounts] " + "; ".join(parts) + (f". Filing: {span}" if span else ""), title, url, None, mod.retrieved_at,
                           "official_register", period=period or None, currency=currency, scope=scope, uncertainty=FILED_NOTE, link_kind=link_kind, record_url=record_url))
    rows[0].update(state="used" if found else "nothing_found", reason=None if found else "no usable figures in the filing")
    return found, rows


SCOPE_OF = {"KONSERN": "consolidated group", "SELSKAP": "standalone company"}
FILED_NOTE = "Figures as filed in the annual accounts. The register returning a filing does not independently verify them."


def filing_link(org: str, period: str | None, scope: str | None, copies: dict[str, str], record_url: str, *, copies_known: bool = True) -> tuple[str, str, str]:
    """(url, link kind, title) for figures read from Regnskapsregisteret.

    ``filing_document`` only when the register itself lists a filed copy for that fiscal year (the direct link to the filing); otherwise ``register_record``: the
    register's data record the figures were read from, which is NOT a copy of the filing and is never labelled as one."""
    year = re.sub(r"\D", "", period or "")[:4]
    what = f"{scope} figures" if scope else "figures (accounting scope not stated)"
    if year and year in copies:
        return copies[year], "filing_document", f"Annual accounts {period} — filed copy listed by Regnskapsregisteret ({what})"
    why = (f"the register lists no filed copy for {period or 'this period'}, so there is no direct link to the filing" if copies_known
           else "not a copy of the filing; whether the register lists a filed copy could not be checked")
    return record_url, "register_record", f"Annual accounts {period or '(period not stated)'} — {what} from the Regnskapsregisteret data record ({why})"


def _class_for(domain: str, own: set[str], news: list[str], regulators: list[str], url: str) -> str | None:
    if domain in own:
        return "company_disclosure"
    if outlet_of(url, regulators):
        return "government_regulator"
    if outlet_of(url, news):
        return "secondary_reporting"
    return None


UNCERTAINTY = {"company_disclosure": "The company's own statement; not independently verified.", "secondary_reporting": "Press report; not an official record.", "government_regulator": None}


async def _read_page(ctx: ConnectorContext, url: str, timeout: float) -> tuple[PageDoc | None, str | None]:
    res = await ctx.fetch(url, connector="chat_lookup", optional=True, accept=HTML_ACCEPT, expect="html", check_robots=True, cache_ttl=ctx.settings.cache_ttl_web_seconds,
                          retry_attempts=0, timeout=timeout)
    if not res.ok:
        return None, {"robots_disallowed": "robots.txt does not allow fetching this page (respected)", "blocked": "the site refused access (not worked around)", "not_found": "the page no longer exists",
                      "gone": "the page no longer exists", "timeout": "the page did not respond in time", "budget_exhausted": "the lookup's request limit was reached"}.get(
            res.classification, f"the page could not be read ({res.classification.replace('_', ' ')})")
    return parse_html(url, res.final_url, res.text(), content_sha256=res.content_sha256, retrieved_at=res.retrieved_at), None


# --------------------------------------------------------------------------------------- lookup --
async def targeted_lookup(s: Any, record: dict[str, Any], question: str, domains: list[str], *, years: list[int] | None = None, recent: bool = False,
                          emit: Emit = None, reason: str = "", use_cache: bool = True) -> Lookup:
    """One bounded, question-focused check of current sources. Never raises for a source problem."""
    emit = emit or (lambda *_a, **_k: None)
    st = s.settings
    started = time.monotonic()
    limit = max(0.5, min(st.chat_lookup_timeout_seconds, st.chat_fresh_timeout_seconds))
    identity = CanonicalIdentity.from_dict(record.get("identity") or {})
    org = identity.org_number or record.get("organisation_number") or ""
    key = (org, fold(clean_ws(question))[:300], tuple(sorted(domains)))
    cache: dict[Any, tuple[float, Lookup]] = s.__dict__.setdefault("_chat_lookups", {})
    hit = cache.get(key) if use_cache else None
    if hit and hit[0] > time.monotonic():
        out = hit[1]
        return Lookup(out.state, out.note, list(out.found), list(out.checked), 0, 0, cached=True)

    out = Lookup("no_results", "")
    deadline = started + limit
    try:
        await asyncio.wait_for(_run(s, out, record, identity, question, domains, years or [], recent, emit, deadline), timeout=limit)
    except TimeoutError:
        out.state = "timeout" if not out.found else "used"
        out.note = (f"The check of current sources was stopped after {limit:.0f} s." + (" What had been read by then is included." if out.found else " Nothing from it is part of this answer."))
    except Exception as exc:  # noqa: BLE001 — a lookup problem must never break the answer
        log.warning(f"chat lookup failed: {type(exc).__name__}")
        out.state, out.note = ("used" if out.found else "unavailable"), "The check of current sources failed part-way" + ("; what was read is included." if out.found else "; nothing from it is used.")
    out.elapsed_ms = int((time.monotonic() - started) * 1000)
    if out.state in ("used", "no_results"):
        cache[key] = (time.monotonic() + st.chat_lookup_cache_seconds, out)
        if len(cache) > 500:
            for k in sorted(cache, key=lambda k: cache[k][0])[:100]:
                cache.pop(k, None)
    if reason and out.state == "used":
        out.note = f"{reason} {out.note}".strip()
    return out


async def _run(s: Any, out: Lookup, record: dict[str, Any], identity: CanonicalIdentity, question: str, domains: list[str], years: list[int], recent: bool, emit: Emit,
               deadline: float) -> None:
    st = s.settings
    budget = CompanyBudget(s.budget, max_requests=4 + 2 * st.chat_lookup_max_pages + st.chat_max_searches, max_seconds=max(2.0, deadline - time.monotonic()) + 2,
                           max_llm_calls=0, max_searches=max(0, st.chat_max_searches))
    ctx = ConnectorContext(org_number=identity.org_number, http=s.http, budget=budget, run_id="chat-lookup", settings=st)

    def checked(row: dict[str, Any]) -> None:
        out.checked.append(row)
        emit("source", row.get("name") or row.get("url") or "source", source={k: row.get(k) for k in ("name", "url", "state", "reason", "kind")})

    # 1 · official filing, for a question about financial results
    tasks: list[Any] = []
    want_official = "financials" in domains and bool(identity.org_number)

    # 2 · a targeted web search over permitted domains
    own = own_domains(record, identity)
    news = allowed_domains(st.secondary_news_domains) if st.enable_secondary_news else []
    regulators = allowed_domains(st.regulatory_domains) if "regulatory" in domains else []
    permitted = sorted(own) + [d for d in regulators if d not in own] + [d for d in news if d not in own]
    web_ok = st.search_enabled and st.chat_max_searches > 0 and bool(identity.legal_name)
    tripped = getattr(s.http, "tripped", {}).get("search")
    web_note = None
    if not st.search_enabled:
        web_note = "Web search is not configured here (no Tavily key, or search is switched off), so only official registers could be checked."
    elif tripped:
        web_note = f"Web search is temporarily unavailable ({tripped}) — no paid fallback is used."
        web_ok = False
    elif st.chat_max_searches <= 0:
        web_note = "Web search is switched off for chat (CHAT_MAX_SEARCHES=0)."
        web_ok = False

    web_failed = False

    async def web() -> None:
        nonlocal web_note, web_failed
        found = out.found  # appended as pages are read, so a time limit keeps what was already verified
        queries = [build_query(question, identity.legal_name or "", domains, years)]
        if st.chat_max_searches > 1:
            queries.append(build_query(question, identity.legal_name or "", [], years).replace('"', ""))  # a broader second try, only if the first finds nothing usable
        before = len(found)
        for qi, query in enumerate(queries):
            if len(found) > before or (qi > 0 and time.monotonic() > deadline - 3):  # a second, broader search only when there is time to read what it finds
                break
            emit("research", "Searching permitted sources for this question" if qi == 0 else "Trying a broader search")
            mod, hits = await search.web_search(ctx, query, count=8, include_domains=permitted[:100], topic="news" if recent else None, days=365 if recent else None)
            out.searches += 1
            if mod.state in ("blocked", "failed"):
                checked({"name": "Web search (Tavily)", "kind": "search", "state": "unavailable", "reason": mod.note or mod.state})
                web_note = f"Web search was unavailable ({mod.note or mod.state}) — no paid fallback is used; this is not evidence that nothing exists."
                web_failed = True
                return
            picks: list[tuple[search.SearchHit, str, str]] = []
            seen: set[str] = set()
            for h in hits:
                dom = registrable_domain(host_of(h.url))
                cls = _class_for(dom, own, news, regulators, h.url)
                if cls is None:
                    checked({"name": dom or h.url, "url": h.url, "state": "skipped", "reason": "not a permitted source; not fetched"})
                    continue
                if dom not in own and not search.hit_matches_company(h, identity.legal_name):
                    checked({"name": dom, "url": h.url, "state": "skipped", "reason": "the result does not mention the company; not fetched"})
                    continue
                if h.url in seen or len(picks) >= st.chat_lookup_max_pages:
                    continue
                seen.add(h.url)
                picks.append((h, dom, cls))
            checked({"name": "Web search (Tavily)", "kind": "search", "state": "used", "results": len(hits), "reason": f"{len(hits)} result(s); {len(picks)} page(s) to read"})
            left = deadline - time.monotonic() - 0.5
            if not picks or left <= 1:
                continue
            emit("research", f"Reading {len(picks)} page{'s' if len(picks) != 1 else ''} that may answer it")
            per_page = max(1.0, min(st.chat_lookup_page_timeout_seconds, left))
            results = await asyncio.gather(*(_read_page(ctx, h.url, per_page) for h, _d, _c in picks), return_exceptions=True)
            for (h, dom, cls), res in zip(picks, results, strict=True):
                if isinstance(res, BaseException):
                    checked({"name": dom, "url": h.url, "state": "unreadable", "reason": f"the page could not be read ({type(res).__name__})"})
                    continue
                doc, why = res
                if doc is None:
                    checked({"name": dom, "url": h.url, "state": "unreadable", "reason": why})
                    continue
                basis, why = ties_to_company(doc, identity, own)
                if basis is None:
                    checked({"name": dom, "url": doc.final_url, "state": "rejected", "reason": why})
                    continue
                passages = relevant_passages(doc, question, identity.legal_name or "", domains)
                if not passages:
                    checked({"name": dom, "url": doc.final_url, "state": "nothing_relevant", "reason": "the page does not address the question"})
                    continue
                day = page_date(doc)
                title = truncate(clean_ws(doc.og.get("title") or doc.title or (doc.headings[0] if doc.headings else dom)), 160)
                body = " … ".join(passages)
                if cls == "government_regulator":
                    _k, stage = classify_stage(f"{title} {body}")
                    kind, text, status = "regulatory", f"{stage.replace('_', ' ')}: {title}" + (f" (published {day})" if day else "") + f". {body}", None
                elif recent or "news" in domains:
                    _k, status = event_status(f"{title}. {body}")
                    kind, text = "event", f"{day or 'undated'} — {title}. {body} [status: {status}]"
                else:
                    kind, text, status = "fact", f"{title}" + (f" (published {day})" if day else "") + f": {body}", None
                unc = UNCERTAINTY.get(cls)
                if not day:
                    unc = ((unc + " ") if unc else "") + "The page states no publication date."
                found.append(Found(kind, text, title, doc.final_url, day, doc.retrieved_at or now_iso(), cls, uncertainty=unc, status=status))
                checked({"name": dom, "url": doc.final_url, "state": "used", "reason": f"tied to the company by {basis}" + (f"; dated {day}" if day else "; undated")})

    async def official() -> None:
        found, rows = await official_accounts(ctx, identity)
        out.found[:0] = found  # the official filing comes first
        for row in rows:
            checked(row)

    if want_official:
        emit("research", "Reading the latest filed annual accounts")
        tasks.append(official())
    if web_ok:
        tasks.append(web())
    elif web_note:
        checked({"name": "Web search (Tavily)", "kind": "search", "state": "not_configured" if not st.search_enabled else "unavailable", "reason": web_note})
    if not tasks:
        out.state = "unavailable" if (tripped and st.search_enabled) else "not_configured"
        out.note = web_note or "No permitted source could answer this kind of question."
        return
    for res in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(res, BaseException):
            log.warning(f"chat lookup part failed: {type(res).__name__}")
    finish(out, st, web_note, web_failed)


def finish(out: Lookup, st: Any, web_note: str | None, web_failed: bool) -> None:
    """The lookup's honest outcome: what was found, or exactly why nothing was."""
    official = next((c for c in out.checked if c.get("kind") == "official"), None)  # the data record of the filed accounts
    pages = [c for c in out.checked if c.get("state") == "used" and c.get("url") and c.get("kind") != "official"]
    searches = f"{out.searches} web search{'es' if out.searches != 1 else ''}"
    if out.found:
        out.state = "used"
        got = [f"{len(pages)} page(s) read" if pages else "", "the filed annual accounts" if official and official.get("state") == "used" else ""]
        out.note = "Checked current sources for this question: " + " and ".join(x for x in got if x) + (f" ({searches}, permitted sources only)." if out.searches else ".")
        if web_note:
            out.note += " " + web_note
        return
    parts: list[str] = []
    if official is not None:
        parts.append(f"Regnskapsregisteret could not be read ({official.get('reason')})." if official.get("state") == "unavailable"
                     else "Regnskapsregisteret holds no usable filed figures for this question.")
    if web_note:
        parts.append(web_note)
    elif out.searches:
        parts.append(f"A targeted search of permitted sources ({searches}) found nothing that answers this question.")
    unavailable = web_failed or (official is not None and official.get("state") == "unavailable")
    if unavailable:
        out.state = "unavailable"
    elif not st.search_enabled and official is None:
        out.state = "not_configured"
    else:
        out.state = "no_results"
    out.note = " ".join(parts) + ("" if unavailable or out.state == "not_configured" else " This is not evidence that the information does not exist.")
