"""Which evidence can answer a custom question?

A question is routed to the evidence that is *about* what was asked: financial questions to the filed accounts, "what was announced" questions to
dated announcements, and questions that no public source can answer (confidential, future, forecast) to a plain statement of that limit.
Saved company facts are never offered as an answer just because they exist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_W = r"(?<!\w)(?:{})(?!\w)"


def _rx(*alts: str) -> re.Pattern[str]:
    return re.compile(_W.format("|".join(alts)), re.I)


# Things no public source can verify: not yet announced, internal, confidential, predicted.
LIMIT = _rx(
    r"confidential\w*", r"non-?public", r"undisclosed", r"unannounced", r"not (?:yet )?(?:been )?(?:announced|public\w*|disclosed)", r"upcoming", r"future",
    r"forecast\w*", r"prognos\w*", r"projection\w*", r"pipeline", r"will (?:win|sign|get|be awarded|announce)", r"going to (?:win|sign)", r"plans? to (?:sign|win|acquire)",
    r"expect\w*", r"negotiat\w*", r"rumou?r\w*", r"insider", r"internal\w*", r"secret\w*", r"fortrolig\w*", r"konfidensiell\w*", r"kommende", r"fremtidig\w*",
    r"hemmelig\w*", r"forhandl\w*", r"forventer", r"intern(?:e|t)?",
)
FINANCIAL = _rx(
    r"revenues?", r"turnover", r"sales", r"profit\w*", r"operating (?:result|profit|income)", r"ebit\w*", r"net (?:income|result|profit)", r"income", r"earnings", r"margins?",
    r"accounts", r"annual (?:result|report|accounts)", r"financial\w*", r"balance sheet", r"equity", r"total assets", r"debt", r"liabilit\w*", r"borrowings?", r"gjeld", r"rentebærende", r"cash", r"reporting period", r"fiscal", r"fy\d{2,4}",
    r"omsetning\w*", r"driftsinntekt\w*", r"driftsresultat\w*", r"resultat\w*", r"overskudd", r"regnskap\w*", r"årsresultat\w*", r"egenkapital\w*",
)
ANNOUNCE = _rx(
    r"announc\w*", r"press releases?", r"newsroom", r"news", r"contracts?", r"discover\w*", r"partnerships?", r"partners?", r"agreements?", r"acquisitions?", r"acquire\w*",
    r"mergers?", r"deals?", r"orders?", r"milestones?", r"launch\w*", r"awarded", r"wins?", r"won", r"investor\w*", r"recent activity", r"activity", r"developments?",
    r"kunngjør\w*", r"kunngjort", r"pressemelding\w*", r"nyhet\w*", r"kontrakt\w*", r"oppdagelse\w*", r"funn", r"partnerskap\w*", r"samarbeid\w*", r"avtale\w*", r"oppkjøp\w*",
    r"tildelt", r"hendelse\w*",
)
PEOPLE = _rx(r"who runs", r"who leads?", r"who(?:'s| is| are) (?:in charge|running|the (?:boss|head))", r"in charge", r"ceo", r"cfo", r"cto", r"coo", r"chief (?:executive|financial|operating|technology)\w*",
             r"leader\w*", r"lead(?:s|ing) the", r"board", r"directors?", r"managing director", r"management", r"chair\w*", r"people", r"executives?", r"head of (?:the )?(?:company|group)",
             r"daglig leder", r"administrerende direktør", r"direktør\w*", r"styre\w*", r"ledelse\w*")
PLACES = _rx(r"where", r"locat\w*", r"offices?", r"operate\w*", r"address\w*", r"adresse\w*", r"sites?")
HIRING = _rx(r"hir\w*", r"jobs?", r"openings?", r"recruit\w*", r"vacanc\w*", r"stilling\w*")
GAPS = _rx(r"not know", r"unknown", r"gaps?", r"missing", r"unverified", r"don'?t know", r"ukjent", r"mangler")
CHANGES = _rx(r"changes?", r"changed", r"new since", r"differ\w*", r"endring\w*", r"updates?")
OVERVIEW = _rx(r"what does", r"what do", r"about (?:the )?(?:company|them|it)", r"describe", r"overview", r"summar\w*", r"company brief", r"brief", r"tell me about",
               r"what is (?:the )?(?:company|this)", r"hva gjør", r"om selskapet", r"beskriv\w*", r"business model")

# Metric families inside a financial question.
METRICS = (
    ("revenue", _rx(r"revenues?", r"turnover", r"sales", r"omsetning\w*", r"driftsinntekt\w*", r"top[- ]?line")),
    ("operating_result", _rx(r"operating (?:result|profit|income)", r"ebit", r"driftsresultat\w*", r"operating")),
    ("annual_result", _rx(r"net (?:income|result|profit)", r"annual result", r"årsresultat\w*", r"bottom[- ]?line", r"profit\w*", r"resultat\w*", r"earnings", r"overskudd")),
    ("total_assets", _rx(r"total assets", r"assets", r"eiendeler")),
    ("equity", _rx(r"equity", r"egenkapital\w*")),
    # total liabilities (what the register files as "sum gjeld") and debt are DIFFERENT measures: a question about debt never selects total liabilities
    ("total_liabilities", _rx(r"liabilit\w*", r"sum gjeld", r"total gjeld", r"(?<!rentebærende )(?<!netto )gjeld")),
    ("debt", _rx(r"debt", r"borrowings?", r"interest[- ]bearing", r"rentebærende", r"netto gjeld")),
    ("cash", _rx(r"cash", r"kontanter", r"bankinnskudd")),
)
PERIOD = _rx(r"reporting period", r"period", r"fiscal year", r"financial year", r"fy\d{2,4}", r"which year", r"regnskapsår", r"regnskapsperiode")
SCOPE_ASK = _rx(r"consolidated", r"group", r"konsern\w*", r"parent")
COMPARE = _rx(r"compar\w*", r"growth", r"vs\.?", r"versus", r"trend", r"previous", r"prior", r"year[- ]over[- ]year", r"yoy", r"change")

WINDOW = re.compile(
    r"(?:last|past|previous|siste|de siste)\s+(?P<n>\d+|a|one|two|three|four|six|twelve|et|ett|to|tre|fire|seks|tolv)?\s*(?P<u>months?|years?|weeks?|days?|måneder?|mnd|år|uker?|dager?|quarters?|kvartal)",
    re.I,
)
_NUM = {"a": 1, "one": 1, "et": 1, "ett": 1, "two": 2, "to": 2, "three": 3, "tre": 3, "four": 4, "fire": 4, "six": 6, "seks": 6, "twelve": 12, "tolv": 12}
_UNIT_DAYS = {"day": 1, "dag": 1, "week": 7, "uke": 7, "month": 30.44, "måned": 30.44, "mnd": 30.44, "quarter": 91.3, "kvartal": 91.3, "year": 365.25, "år": 365.25}

# Words that name an announcement category and the event types that belong to it.
CATEGORIES = (
    ("contracts", _rx(r"contracts?", r"kontrakt\w*", r"orders?", r"awarded", r"tildelt", r"agreements?", r"avtale\w*"), {"contract"}),
    ("discoveries", _rx(r"discover\w*", r"oppdagelse\w*", r"funn"), {"discovery"}),
    ("partnerships", _rx(r"partnerships?", r"partner\w*", r"partnerskap\w*", r"samarbeid\w*", r"alliance\w*"), {"partnership"}),
    ("acquisitions", _rx(r"acquisitions?", r"acquire\w*", r"mergers?", r"oppkjøp\w*", r"fusjon\w*"), {"acquisition", "restructuring"}),
    ("results", _rx(r"results?", r"earnings", r"quarterly", r"resultat\w*"), {"results"}),
    ("leadership changes", _rx(r"leadership", r"appointments?", r"new ceo", r"ledelse\w*"), {"leadership"}),
    ("funding", _rx(r"funding", r"financing", r"capital raise", r"investment round"), {"funding"}),
    ("project and production updates", _rx(r"milestones?", r"projects?", r"production", r"launch\w*"), {"project", "production"}),
)
FIRST_SENTENCE = re.compile(r"^(?:list|show|give|tell|what|which|has|have|did|does|is|are)\b", re.I)


@dataclass
class Route:
    kinds: list[str] = field(default_factory=list)  # limitation | financial | announcements | people | locations | hiring | changes | overview | other
    window_days: int | None = None
    window_text: str | None = None
    metrics: list[str] = field(default_factory=list)
    wants_period: bool = False
    wants_scope: bool = False
    wants_comparison: bool = False
    categories: list[tuple[str, set[str]]] = field(default_factory=list)
    limit_reason: str | None = None


def time_window(question: str) -> tuple[int | None, str | None]:
    m = WINDOW.search(question)
    if m:
        raw = (m.group("n") or "1").lower()
        n = int(raw) if raw.isdigit() else _NUM.get(raw, 1)
        unit = m.group("u").lower().rstrip("s")
        unit = {"måneder": "måned", "måned": "måned", "uker": "uke", "dager": "dag"}.get(m.group("u").lower(), unit)
        days = _UNIT_DAYS.get(unit) or _UNIT_DAYS.get(unit.rstrip("s")) or 365.25
        count = f"{n} " if n != 1 else ""
        unit_word = {"måned": "month", "uke": "week", "dag": "day", "år": "year", "mnd": "month", "kvartal": "quarter"}.get(unit, unit)
        return int(round(n * days)), f"the last {count}{unit_word}{'s' if n != 1 else ''}"
    if re.search(r"(?<!\w)(?:this year|i år)(?!\w)", question, re.I):
        return 365, "this year"
    return None, None


def route_question(question: str) -> Route:
    q = question.strip()
    r = Route()
    r.window_days, r.window_text = time_window(q)
    limit = LIMIT.search(q)
    if limit:
        r.kinds = ["limitation"]
        r.limit_reason = limit.group(0)
        return r
    fin, ann = bool(FINANCIAL.search(q)), bool(ANNOUNCE.search(q))
    if fin:
        r.kinds.append("financial")
        r.metrics = [key for key, rx in METRICS if rx.search(q)]
        # "operating profit" names the operating result only; plain "profit" means the annual (net) result
        if "operating_result" in r.metrics and "annual_result" in r.metrics and not re.search(r"net|annual|årsresultat|bottom", q, re.I):
            r.metrics.remove("annual_result")
        r.wants_period = bool(PERIOD.search(q))
        r.wants_scope = bool(SCOPE_ASK.search(q))
        r.wants_comparison = bool(COMPARE.search(q))
    if ann and not (fin and not re.search(r"announc\w*|press release|newsroom|news|contract|discover|partner|acqui|kunngj|pressemelding|nyhet", q, re.I)):
        r.kinds.append("announcements")
        r.categories = [(label, types) for label, rx, types in CATEGORIES if rx.search(q)]
    for kind, rx in (("people", PEOPLE), ("locations", PLACES), ("hiring", HIRING), ("changes", CHANGES), ("gaps", GAPS), ("overview", OVERVIEW)):
        if not r.kinds and rx.search(q):
            r.kinds.append(kind)
    if not r.kinds:
        r.kinds = ["other"]
    return r
