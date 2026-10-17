"""Step 1 of the chat pipeline — *understand the request*: what kind of question is this, which period does it name, and which source domains can answer it.

Pure functions over the question text (no network, no model), so the behaviour is deterministic and testable. The result steers evidence selection,
which research is worth running, and which validations apply:

* ``source_audit``         "Which sources did you actually check …?"  → answered from the saved/last-run source status records, never from company facts.
* ``financial_comparison`` "Which figures changed most …?"            → computed from the filed accounts of two periods (``fincompare``).
* ``future_actual``        "What is its exact revenue in 2035?"      → an actual result for a period that has not ended: never answered with another year.
* ``forecast``             "What is the revenue forecast for 2027?"  → only labelled estimates/targets from accessible evidence, or an honest "none found".
* ``recent``               "What happened recently?"                  → dated events with an explicit status (announced / signed / completed …).
* ``general``              everything else (routed by ``question_router``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .question_router import FINANCIAL, METRICS

_YEAR = re.compile(r"(?<![\d.,])((?:19|20)\d{2})(?![\d]|\s?(?:%|nok|usd|eur))", re.I)
_FY = re.compile(r"\bFY\s?'?(\d{2,4})\b", re.I)

ACTUAL_WORDS = re.compile(r"(?<!\w)(?:actual|exact|reported|real|final|audited|filed|booked|achieved|made|was|were|had|did|earned|generated|posted)(?!\w)", re.I)
FORECAST_WORDS = re.compile(r"(?<!\w)(?:forecast\w*|project(?:ed|ion|ions)|outlook|guidance|target\w*|estimat\w*|expect\w*|predict\w*|prognos\w*|anticipat\w*|plan(?:ned|s)?|ambition\w*|budget\w*|will)(?!\w)", re.I)
FUTURE_WORDS = re.compile(r"(?<!\w)(?:will|going to|next year|in the future|upcoming|coming year|fremtid\w*|neste år|kommende)(?!\w)", re.I)

SOURCE_AUDIT = re.compile(
    r"(?:which|what|list|show)\b.{0,40}\b(?:sources?|registers?|databases?|connectors?|records?)\b.{0,50}\b(?:check\w*|search\w*|use[d]?|consult\w*|look\w*|query|queried|cover\w*|read)\b"
    r"|\b(?:sources?|registers?)\b.{0,30}\b(?:did you|have you|were|was|are)\b.{0,30}\b(?:check\w*|search\w*|use[d]?|consult\w*|look\w*)\b"
    r"|\bwhat (?:did|have) you (?:actually )?(?:check\w*|search\w*|look\w*)\b|\bwhere did you (?:look|search|check)\b|\bhow (?:do|did) you know\b.{0,30}\bsources?\b"
    r"|\bwhat(?:'s| is| was| has been) (?:the )?(?:coverage|source status)\b|\bwhat was (?:not )?checked\b|\bwhat (?:could|can)(?:'t| ?not) you (?:check|verify)\b",
    re.I,
)
COMPARE_WORDS = re.compile(
    r"(?<!\w)(?:compar\w*|changed?|changes?|difference\w*|differ\w*|growth|grew|declin\w*|decreas\w*|increas\w*|vs\.?|versus|year[- ]over[- ]year|yoy|previous (?:year|period)|prior (?:year|period)|"
    r"last year|trend\w*|moved|up or down|delta)(?!\w)", re.I)
PERIOD_WORDS = re.compile(r"(?<!\w)(?:both (?:periods|years)|two (?:periods|years)|previous|prior|last year|year[- ]over[- ]year|yoy|period|year)(?!\w)", re.I)
MOST_WORDS = re.compile(r"(?<!\w)(?:most|biggest|largest|greatest|top|major|significant\w*|strongest)(?!\w)", re.I)
BY_AMOUNT = re.compile(r"(?<!\w)(?:in (?:money|amount|absolute|nok|usd|eur|kroner|dollars?)|absolute|monetary|biggest amount|largest amount|by amount|in value)(?!\w)", re.I)
BY_PERCENT = re.compile(r"(?<!\w)(?:percent\w*|%|relative\w*|proportion\w*|prosent\w*)(?!\w)", re.I)
RESULTS_WORDS = re.compile(r"(?<!\w)(?:results?|figures?|numbers|performance|financials?|accounts|key metrics)(?!\w)", re.I)
RECENT = re.compile(r"(?<!\w)(?:latest|recent\w*|newest|just|happened|news|announce\w*|developments?|what(?:'s| is) new|this (?:week|month|year|quarter)|nylig|siste|nyeste|hendt)(?!\w)", re.I)

# What each domain is called in the saved research record and in the answer.
DOMAIN_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ip", re.compile(r"(?<!\w)(?:patent\w*|trademark\w*|designs?|design rights?|ip rights?|intellectual property|patentstyret|varemerke\w*)(?!\w)", re.I)),
    ("ownership", re.compile(r"(?<!\w)(?:own(?:s|ed|er|ers|ership)?|shareholder\w*|stake\w*|aksjonær\w*|eier\w*|parent|subsidiar\w*|group structure)(?!\w)", re.I)),
    ("regulatory", re.compile(r"(?<!\w)(?:regulat\w*|licen[cs]\w*|fines?|sanction\w*|investigat\w*|compliance|enforcement|decisions?|tilsyn\w*|vedtak\w*|konsesjon\w*|legal issues?|lawsuit\w*)(?!\w)", re.I)),
    ("hiring", re.compile(r"(?<!\w)(?:hiring|jobs?|openings?|vacanc\w*|recruit\w*|stilling\w*)(?!\w)", re.I)),
    ("news", re.compile(r"(?<!\w)(?:news|announce\w*|press|newsroom|developments?|contracts?)(?!\w)", re.I)),
    ("financials", FINANCIAL),
)


@dataclass
class Intent:
    kind: str = "general"  # general | source_audit | financial_comparison | future_actual | forecast | recent
    years: list[int] = field(default_factory=list)  # every year the question names
    future_years: list[int] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)  # source domains the question is about (ip, ownership, regulatory, hiring, news, financials)
    metrics: list[str] = field(default_factory=list)
    rank_by: str = "percent"  # percent | amount (financial_comparison)
    wants_both_periods: bool = False
    mentions_metric: bool = False


def years_in(question: str) -> list[int]:
    out: list[int] = []
    for m in _YEAR.finditer(question):
        out.append(int(m.group(1)))
    for m in _FY.finditer(question):
        raw = m.group(1)
        out.append(int(raw) if len(raw) == 4 else 2000 + int(raw))
    return sorted(set(out))


def period_has_ended(year: int, today: date) -> bool:
    """Annual accounts for a fiscal year can exist only after that year has ended."""
    return year < today.year


def classify(question: str, *, today: date | None = None, prior_question: str = "") -> Intent:
    today = today or date.today()
    q = question.strip()
    intent = Intent()
    intent.years = years_in(q)
    intent.future_years = [y for y in intent.years if not period_has_ended(y, today)]
    intent.domains = [name for name, rx in DOMAIN_WORDS if rx.search(q)]
    intent.metrics = [key for key, rx in METRICS if rx.search(q)]
    intent.mentions_metric = bool(intent.metrics) or bool(FINANCIAL.search(q))

    # A short follow-up ("and the year before?") continues the previous financial question.
    follow = bool(prior_question) and len(q.split()) <= 8 and not intent.domains and not SOURCE_AUDIT.search(q)
    if follow and FINANCIAL.search(prior_question) and COMPARE_WORDS.search(q + " " + prior_question):
        intent.mentions_metric = True

    if SOURCE_AUDIT.search(q):
        intent.kind = "source_audit"
        return intent

    wants_forecast = bool(FORECAST_WORDS.search(q)) and not re.search(r"(?<!\w)will (?:you|it|be able)(?!\w)", q, re.I)
    if intent.future_years and (intent.mentions_metric or ACTUAL_WORDS.search(q) or wants_forecast):
        # A figure for a period that has not ended cannot be an actual result. Asking for a forecast/target is a different (labelled) question.
        intent.kind = "forecast" if wants_forecast and not re.search(r"(?<!\w)(?:actual|exact|reported|real|final)(?!\w)", q, re.I) else "future_actual"
        return intent
    if wants_forecast and intent.mentions_metric and not intent.years and re.search(r"(?<!\w)(?:forecast\w*|project(?:ed|ion|ions)|outlook|guidance|prognos\w*)(?!\w)", q, re.I):
        intent.kind = "forecast"
        return intent

    if (intent.mentions_metric or RESULTS_WORDS.search(q)) and COMPARE_WORDS.search(q) and not (set(intent.domains) - {"financials"}):
        intent.kind = "financial_comparison"
        intent.wants_both_periods = bool(PERIOD_WORDS.search(q))
        if BY_AMOUNT.search(q) and not BY_PERCENT.search(q):
            intent.rank_by = "amount"
        return intent
    if follow and FINANCIAL.search(prior_question) and COMPARE_WORDS.search(q):
        intent.kind = "financial_comparison"
        return intent

    if RECENT.search(q) and not intent.mentions_metric:
        intent.kind = "recent"
    return intent


# ----------------------------------------------------------------------------- company mentions --
_CAP_STOP = {
    "what", "who", "which", "when", "where", "why", "how", "is", "are", "was", "were", "does", "did", "do", "has", "have", "had", "can", "could", "should", "would", "will", "tell", "show", "give",
    "list", "compare", "find", "check", "explain", "summarise", "summarize", "describe", "and", "or", "the", "a", "an", "its", "it", "their", "this", "that", "these", "those", "also", "now",
    "please", "cognis", "norway", "norwegian", "nok", "usd", "eur", "fy", "ceo", "cfo", "ai", "ok", "yes", "no", "revenue", "latest", "recent", "i", "we", "you", "my", "our", "about", "for", "of",
    "in", "on", "at", "to", "from", "with", "by", "any", "all", "some", "other", "another", "same", "use", "using", "reuse", "instead", "ignore", "then", "so", "but", "if", "not", "whose", "how's",
    "q1", "q2", "q3", "q4", "ebitda", "ebit", "ipo", "esg", "ted", "nav", "brreg", "patentstyret", "doffin", "tavily", "groq",
    # ordinary sentence-opening words (instructions and report vocabulary) that a registered business may also be called: never a company on their own
    "include", "includes", "including", "exclude", "identify", "provide", "clearly", "distinguish", "state", "report", "present", "research", "analyse", "analyze", "outline", "highlight",
    "mention", "note", "focus", "get", "make", "see", "read", "add", "fetch", "extract", "calculate", "estimate", "rank", "sort", "break", "write", "draft", "prepare", "generate", "create",
    "return", "display", "contrast", "evaluate", "assess", "review", "verify", "confirm", "consider", "suggest", "recommend", "summary", "overview", "annual", "financial", "net", "total",
    "source", "sources", "link", "links", "period", "reporting", "consolidated", "company", "group", "accounts", "results", "result", "answer", "keep", "stay", "never", "always", "only",
    "just", "first", "next", "last", "between", "look", "pull", "bring", "gather", "collect", "locate", "name", "detail", "details", "separate", "split", "cite", "quote",
    "hva", "hvem", "hvordan", "fortell", "vis", "gi", "sammenlign", "oppsummer", "inkluder", "hvilke", "hvor", "når", "kan", "har", "er", "finn", "forklar",
}
_SENTENCE_START = re.compile(r"(?:^|[.!?:;\n])[\s\"'“‘(\[\-•*\d.)]*$")
_CAP_WORD = re.compile(r"[A-ZÆØÅ][\wæøåÆØÅ&.'\-]*")


def _opens_sentence(question: str, start: int) -> bool:
    return bool(_SENTENCE_START.search(question[:start]))


def capitalised_names(question: str, *, limit: int = 3, skip_openers: bool = False) -> list[str]:
    """Proper-noun-like candidates in the question ("Equinor", "DNB Bank", "Hydro"), most specific first. Only *candidates*: the register decides what is real.

    ``skip_openers``: a single ordinary capitalised word that merely begins a sentence ("Include the reporting period", "Clearly distinguish …") is capitalised by grammar,
    not because it is a name, so it is not a candidate. Used when the chat already has an active company; a company that begins the sentence still counts when it is
    followed by another name word or a legal form."""
    tokens = list(_CAP_WORD.finditer(question))
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        word = re.sub(r"['’]s$", "", t.group(0)).strip(".'-")
        if word.lower() in _CAP_STOP or len(word) < 2:
            i += 1
            continue
        j = i
        parts = [word]
        while j + 1 < len(tokens) and tokens[j + 1].start() - tokens[j].end() == 1 and tokens[j + 1].group(0).strip(".'-").lower() not in _CAP_STOP:
            j += 1
            parts.append(re.sub(r"['’]s$", "", tokens[j].group(0)).strip(".'-"))
        single_opener = skip_openers and j == i and _opens_sentence(question, t.start()) and word[1:].islower()
        if not single_opener:
            out.append(" ".join(parts))
        i = j + 1
    seen: set[str] = set()
    uniq = [n for n in out if not (n.lower() in seen or seen.add(n.lower()))]
    return sorted(uniq, key=lambda n: -len(n.split()))[:limit]


# ------------------------------------------------------------------------------------- event status --
_STATUS_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("dividend_paid", "Dividend paid", re.compile(r"\bdividend\b.{0,60}\b(?:was paid|has been paid|paid out|payment (?:made|completed)|utbetalt)\b|\b(?:paid|utbetalte)\b.{0,30}\bdividend", re.I)),
    ("dividend_announced", "Dividend announced or proposed (not yet paid)", re.compile(r"\b(?:dividend|utbytte)\b", re.I)),
    ("transfer_completed", "Transaction completed", re.compile(r"\b(?:completes?|completed|has completed|closed|closing completed|finalis(?:es|ed)|finaliz(?:es|ed)|fullfører|fullført|gjennomført)\b.{0,60}\b(?:acquisition|sale|transaction|transfer|divestment|merger|deal|oppkjøp|salg)\b|"
                                                       r"\b(?:acquisition|sale|transaction|transfer|divestment|merger|deal)\b.{0,40}\b(?:completed|closed|finalis\w*|finaliz\w*|fullført)\b", re.I)),
    ("agreement_signed", "Agreement signed (transfer or closing not yet confirmed)", re.compile(r"\b(?:signs?|signed|enters? into|entered into|agrees? to|agreed to|has agreed|inngår|signert|undertegnet)\b.{0,80}\b(?:agreement|contract|deal|sale|acquisition|purchase|divest|partnership|avtale|kontrakt)\b|"
                                                                                                         r"\b(?:agreement|contract|deal)\b.{0,40}\b(?:signed|entered|inngått)\b", re.I)),
    ("production_started", "Production started", re.compile(r"\b(?:starts?|started|begins?|began|commence[sd]?|on stream|first (?:oil|gas)|produksjonsstart|startet produksjon)\b.{0,40}\b(?:production|produksjon|oil|gas)\b|\bproduction\b.{0,20}\b(?:starts?|started|begins?|began|commence[sd]?)\b|\bon stream\b|\bfirst (?:oil|gas)\b", re.I)),
    ("discovery_announced", "Discovery announced (not a field development or production)", re.compile(r"\b(?:discover(?:y|ies|ed|s)?|makes? (?:a )?discovery|funn|oppdagelse)\b", re.I)),
    ("investment_decision", "Investment decision or plan submitted", re.compile(r"\b(?:final investment decision|fid|plan for development|pdo|submits?|submitted|leverer)\b", re.I)),
    ("planned", "Planned or proposed (not yet done)", re.compile(r"\b(?:plans? to|planned|intends? to|proposes?|proposed|will (?!be paid)|expects? to|aims? to|seeks? to|is considering|vil\b|planlegger)\b", re.I)),
)


def event_status(text: str, event_type: str | None = None) -> tuple[str, str]:
    """(key, label): what an announcement actually says has happened. An intended outcome is never described as an accomplished one."""
    t = text or ""
    for key, label, rx in _STATUS_RULES:
        if rx.search(t):
            # a discovery notice that mentions "production" only in passing is still a discovery
            return key, label
    if event_type == "results":
        return "reported", "Reported results"
    return "announced", "Announced"
