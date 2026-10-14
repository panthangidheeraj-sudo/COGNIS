"""Is this event Major, Relevant or Routine — and why?

Deterministic and explainable. The decision uses only what the evidence says (headline, summary, kind of source, date) and, for the size of an
amount, the company's own last filed revenue *in the same currency*. Amounts are never converted between currencies.

* **Major**    – likely to change an assessment of the company: acquisitions and divestments, material contracts and orders, financial results and
                 guidance, discoveries, top-level leadership changes, large capital raises, production start/stop and serious operational events,
                 restructurings, final investment decisions, serious regulatory actions.
* **Relevant** – meaningful but not decision-changing: smaller partnerships, expansions and new locations, mid-level appointments, product launches,
                 routine regulatory steps, ownership and name changes recorded in the register.
* **Routine**  – bookkeeping and noise: establishments and registrations in the register, invitations, webinars, marketing, generic notices.

Registry facts never reach Major on their own. A press release that announces what the register later records is its own, separately judged event.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..core.util import fold

MAJOR, RELEVANT, ROUTINE = "major", "relevant", "routine"
TIERS = (MAJOR, RELEVANT, ROUTINE)
TIER_LABEL = {MAJOR: "Major", RELEVANT: "Relevant", ROUTINE: "Routine"}

MAJOR_MIN_SCORE = 58
RELEVANT_MIN_SCORE = 34
REGISTRY_SCORE_CAP = 49  # a register entry can be Relevant at most

# Event types the timeline uses (frontend ``TimelineEventType``).
TYPES = ("filing", "jobs", "leadership", "contract", "acquisition", "location", "announcement", "registration", "funding",
         "results", "partnership", "discovery", "project", "production", "regulatory", "restructuring")

BASE_SCORE = {"acquisition": 70, "restructuring": 60, "discovery": 62, "contract": 58, "results": 56, "funding": 48, "leadership": 46, "partnership": 44,
              "production": 44, "project": 42, "regulatory": 36, "location": 30, "announcement": 16, "jobs": 10, "filing": 25, "registration": 4}
PRIORITY = ("acquisition", "restructuring", "results", "contract", "discovery", "funding", "leadership", "regulatory", "partnership", "production", "project",
            "location", "announcement")


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.I)


# (pattern, weight): 2 = decisive wording, 1 = typical wording, 0.5 = ambiguous on its own.
PATTERNS: dict[str, list[tuple[re.Pattern[str], float]]] = {
    "acquisition": [
        (_rx(r"\bacquir(?:e|es|ed|ing)\b", r"\bacquisitions?\b", r"\btake[- ]?overs?\b", r"\bmerger\b", r"\bmerg(?:es|ed|ing)\s+with\b", r"\bdivest(?:s|ed|ing|ment|iture)?\b",
             r"\bbuy[- ]?outs?\b", r"\bdemerger\b", r"oppkjøp", r"\bfusjon", r"\bfisjon", r"\bavhend", r"\bselger seg ut\b", r"\bovertar\b"), 2),
        (_rx(r"\bk(?:jøper|jøpte|jøpt)\b.{0,30}\b(?:konkurrent|selskap|virksomhet|bedrift|forhandler|konsern|eierandel|aksjer|aksjene|rival)",
             r"\b(?:buys|bought|purchases?|purchased)\b.{0,30}\b(?:competitor|rival|company|business|stake|shares|dealer|group)\b", r"\bkjøpt opp\b", r"\bkjøper opp\b"), 2),
        (_rx(r"\bsells?\s+(?:its|the|a)\b.{0,40}\b(?:business|stake|subsidiary|company|assets|shares)\b", r"\beierandel\b", r"\bstake in\b", r"\bkjøper (?:opp|selskap|aksjer|\d+\s?%)",
             r"\bbuys\b.{0,30}\b(?:company|stake|business)\b"), 1),
        (_rx(r"\bkjøper\b"), 0.5),
    ],
    "restructuring": [
        (_rx(r"\bredundanc", r"\blay[- ]?offs?\b", r"\bjob cuts?\b", r"\bcuts?\s+\d+\s+jobs\b", r"nedbemann", r"permitter", r"\boppsigelser\b", r"\brestructur", r"\bomstilling\b",
             r"\bbankrupt", r"\bkonkurs\b", r"\binsolven", r"\bnedleggelse\b", r"\blegger ned\b", r"\bprofit warning\b", r"\bresultatvarsel\b", r"\bimpairment\b", r"\bnedskrivning",
             r"\bclos(?:es|ing|ure of)\b.{0,30}\b(?:plant|factory|facility|mine|site|office|operations)\b", r"\bstreik\b", r"\blockout\b", r"\bindustrial action\b", r"\bworkers?\s+(?:go on\s+)?strike\b"), 2),
    ],
    "results": [
        (_rx(r"\b(?:first|second|third|fourth|q[1-4]|[1-4]q|half[- ]year|full[- ]year|annual|quarterly|interim)\b[\w\s,]{0,16}\b(?:results?|earnings|report)\b",
             r"\breports?\b[\w\s,]{0,30}\b(?:results?|earnings)\b", r"\bfinancial results\b", r"kvartalsresultat", r"\b[1-4]\.?\s?kvartal", r"delårsrapport", r"årsrapport", r"årsresultat",
             r"halvårsrapport", r"\bresultat(?:er)?\s+(?:for|fra)\b", r"\bearnings\b", r"\bguidance\b"), 2),
        (_rx(r"\bdividend\b", r"\butbytte\b", r"\bannual report\b", r"\bårsregnskap\b", r"\bcapital markets (?:day|update)\b", r"\bkapitalmarkedsdag\b", r"\bsustainability report\b",
             r"\bbærekraftsrapport\b"), 1),
    ],
    "contract": [
        (_rx(r"\bawarded\b", r"\bwins?\b.{0,40}\b(?:order|contract|deal|tender|assignment)\b", r"\bsecures?\b.{0,40}\b(?:order|contract|deal|assignment)\b",
             r"\bcontracts?\b", r"\bpurchase orders?\b", r"\bframework agreements?\b", r"\bsupply agreements?\b", r"\bkontrakt", r"\btildelt\b", r"\btildeling\b", r"\brammeavtale",
             r"\bleveranseavtale", r"\bvinner\b.{0,40}\b(?:kontrakt|anbud|ordre|oppdrag)"), 2),
        (_rx(r"\border(?:s)?\s+(?:worth|valued|for|of)\b", r"\bordre\b", r"\banbud\b", r"\boppdrag\b", r"\bbestilling\b"), 1),
    ],
    "discovery": [
        (_rx(r"\bdiscover(?:y|ies|s|ed)\b", r"\b(?:makes?|made)\s+(?:a\s+)?(?:significant\s+|new\s+)?(?:oil\s+|gas\s+|mineral\s+)?(?:find|strike)\b", r"\bgjør\s+(?:et\s+)?funn\b",
             r"\bfunn\b", r"\bpåviser\b", r"\bresource (?:estimate|upgrade)\b", r"\bressursestimat\b", r"\bdrill results?\b", r"\bboreresultat"), 2),
    ],
    "funding": [
        (_rx(r"\bprivate placement\b", r"\brights issue\b", r"\bshare issue\b", r"\bipo\b", r"\bemisjon", r"\bkapitalforhøyelse", r"\bbond (?:issue|offering|placement)\b", r"\bobligasjonslån\b",
             r"\bseries [a-e]\b", r"\brefinanc", r"\braises?\b.{0,40}\b(?:million|billion|mnok|musd|meur|mrd|mill)\b", r"\bfunding round\b"), 2),
        (_rx(r"\bfinancing\b", r"\bcredit facility\b", r"\bkredittfasilitet\b", r"\bloan\b", r"\blån\b", r"\bshare buy[- ]?back\b", r"\btilbakekjøp\b", r"\bfunding\b", r"\bfinansiering\b"), 1),
    ],
    "leadership": [],  # handled by ``_leadership`` (needs role + action, either order)
    "regulatory": [
        (_rx(r"\bfined\b", r"\bfines\b", r"\bovertredelsesgebyr\b", r"\bilagt\b", r"\binvestigation\b", r"\betterforsk", r"\blicen[cs]e\s+(?:award|granted)", r"\btildelt\b.{0,20}\b(?:lisens|konsesjon)",
             r"\bprospectus\b", r"\bprospekt\b", r"\bdelisting\b", r"\bkonkurransetilsynet\b", r"\bfinanstilsynet\b", r"\bregulator\b"), 2),
        (_rx(r"\bregulatory\b", r"\bfiling\b", r"\bfiled\b", r"\blisting\b", r"\bnotering\b", r"\blicen[cs]e\b", r"\blisens\b", r"\btillatelse\b", r"\bpermit\b", r"\bconcession\b", r"\bkonsesjon\b",
             r"\bapproval\b", r"\bgodkjenning\b", r"\blawsuit\b", r"\bsøksmål\b", r"\bcourt\b", r"\bdomstol\b", r"\bappeal\b", r"\banke\b"), 1),
    ],
    "partnership": [
        (_rx(r"\bjoint[- ]venture\b", r"\bJV\b", r"\bstrategic (?:partnership|alliance|collaboration|cooperation)\b", r"\bstrategisk(?:e)? (?:partnerskap|samarbeid|allianse)"), 2),
        (_rx(r"\bpartnership\b", r"\bpartner(?:s|ed|ing)?\s+with\b", r"\bcollaborat", r"\bcooperat", r"\bmemorandum of understanding\b", r"\bmou\b", r"\bletter of intent\b",
             r"\bsamarbeid", r"\bpartnerskap\b", r"\bintensjonsavtale\b", r"\ballianse\b", r"\bteams? up\b", r"\bagreements?\b", r"\bavtale\b", r"\bdeal\b"), 1),
    ],
    "production": [
        (_rx(r"\bfirst (?:oil|gas|power|production)\b", r"\bproduction (?:start|halt|stop|record|resumes?)\b", r"\bstarts?\s+(?:up\s+)?production\b", r"\bproduksjonsstart\b", r"\bstarter\s+(?:opp\s+)?produksjon\b", r"\bproduksjonsstans\b", r"\bshut[- ]?downs?\b",
             r"\boutage\b", r"\bdriftsstans\b", r"\brecall\b", r"\btilbakekall", r"\bon[- ]?stream\b", r"\bstart[- ]up of\b", r"\bidriftsett"), 2),
        (_rx(r"\bproduction\b", r"\bproduksjon\b", r"\boutput\b", r"\bthroughput\b", r"\bcapacity\b", r"\bkapasitet\b", r"\bcommission(?:ing|ed)\b", r"\bhalts?\b", r"\bsuspend", r"\bstans(?:er|et)?\b"), 1),
    ],
    "project": [
        (_rx(r"\bfinal investment decision\b", r"\bFID\b", r"\binvesteringsbeslutning\b", r"\bPDO\b", r"\bPUD\b", r"\bplan for (?:utbygging|development)\b", r"\bproject (?:completed|milestone|sanction)\b",
             r"\bbyggestart\b", r"\bconstruction (?:start|begins|starts)\b", r"\bground[- ]?breaking\b", r"\bsanction(?:s|ed)?\b.{0,30}\bproject\b"), 2),
        (_rx(r"\bproject\b", r"\bprosjekt", r"\bmilestone\b", r"\bmilepæl\b", r"\bconstruction\b", r"\bcompleted\b", r"\bfullført\b", r"\bdelivery of\b", r"\blevering av\b", r"\bferdigstill"), 1),
    ],
    "location": [
        (_rx(r"\bnew (?:office|factory|plant|warehouse|store|branch|site|facility|location|hq|headquarters)\b", r"\bnytt (?:kontor|lager|hovedkontor)\b", r"\bny (?:fabrikk|butikk|avdeling|lokasjon|filial)\b",
             r"\bopens?\b.{0,30}\b(?:office|plant|factory|store|facility|branch)\b", r"\båpner\b", r"\bnytt kontor\b", r"\brelocat", r"\bflytter\b", r"\bexpands?\b", r"\bexpansion\b", r"\bekspander",
             r"\butvider\b", r"\betablerer\b", r"\bestablish(?:es|ed|ing)?\s+(?:a\s+|an\s+)?(?:new\s+)?(?:office|presence|subsidiary|branch)\b"), 1),
    ],
}

# Wording that makes an announcement ordinary, whatever else it says.
ROUTINE_MARKERS = _rx(r"\bwebinar\b", r"\bwebcast\b", r"\bpodcast\b", r"\bnewsletter\b", r"\bnyhetsbrev\b", r"\bseminar\b", r"\bworkshop\b", r"\binvitation\b", r"\binvitasjon\b", r"\bsave the date\b",
                      r"\bregister now\b", r"\bmeet us\b", r"\bvisit us\b", r"\bexhibit", r"\bmesse\b", r"\bkarrieredag", r"\bcareer day\b", r"\bjob opening", r"\bledig stilling", r"\bvacanc", r"\bblog\b",
                      r"\btips\b", r"\bguide\b", r"\bhow to\b", r"\bhvordan\b", r"\bcase study\b", r"\bkundehistorie", r"\bcustomer story\b", r"\binterview\b", r"\bintervju\b", r"\bopening hours\b",
                      r"\båpningstider\b", r"\bholiday\b", r"\bjulehilsen\b", r"\bchristmas\b", r"\bcongratulat", r"\bgratulerer\b", r"\bsponsor", r"\bdonat", r"\bannual general meeting\b",
                      r"\bgeneralforsamling\b", r"\bnotice (?:of|to) (?:the )?(?:annual|extraordinary)\b", r"\binnkalling til\b", r"\bto host\b", r"\bholder (?:presentasjon|webcast)\b",
                      r"\bconference call\b", r"\bresults presentation\b", r"\bpresentation of\b", r"\bpresentasjon av\b", r"\bmandatory notification of trade\b", r"\bmeldepliktig handel\b",
                      r"\bprimary insider", r"\bfinancial calendar\b", r"\bfinanskalender\b")
# A prize or a certification is not a contract award.
AWARD_NOT_CONTRACT = _rx(r"\btildelt\b.{0,30}\b(?:pris|stipend|sertifisering|utmerkelse)", r"\bawarded\b.{0,30}\b(?:prize|certificat|accreditation|ranking|award for|best)", r"\baward[- ]winning\b",
                         r"\bwins?\b.{0,20}\baward\b")
MAJOR_FUNDING = _rx(r"\bipo\b", r"\brights issue\b", r"\bprivate placement\b", r"\brettet emisjon\b", r"\bemisjon\b", r"\bbond (?:issue|offering|placement)\b", r"\bobligasjonslån\b")
PRODUCT_LAUNCH = _rx(r"\blaunch(?:es|ed)?\b", r"\blanserer\b", r"\bnew product\b", r"\bnytt produkt\b", r"\bunveils?\b", r"\bintroduces?\b")
CERTIFICATION = _rx(r"\bcertif", r"\bsertifis", r"\baccreditation\b", r"\bsustainab", r"\bbærekraft", r"\bprize\b", r"\bpris\b", r"\baward\b", r"\butmerkelse\b")

_TOP_ROLE = r"(?:ceo|cfo|coo|cto|cio|chair(?:man|woman|person)?|president|managing director|chief\s+\w+\s+officer|executive vice president|evp|konsernsjef|administrerende direktør|adm\.?\s?dir\.?|daglig leder|finansdirektør|styreleder|styrets leder|konserndirektør)"
_OTHER_ROLE = r"(?:director|head of|vice president|vp|general manager|manager|direktør|sjef|styremedlem|board member)"
_ACTION = r"(?:appoint(?:s|ed|ment)?|names?|named|nominates?|hires?|hired|elect(?:s|ed)?|resign(?:s|ed|ation)?|steps? down|to step down|leaves?|retire(?:s|ment)?|succeed(?:s|ed)?|ansetter|ansatt|utnevner|utnevnt|konstituert|går av|fratrer|trer av|slutter|velges|valgt|ansettes)"
_NEW = r"(?:new|ny|nye)"
_GAP = r"(?:\s+[\w.\-’']+){0,6}?"
LEADERSHIP_TOP = _rx(rf"\b{_ACTION}\b{_GAP}\s+{_TOP_ROLE}\b", rf"\b{_TOP_ROLE}\b{_GAP}\s+{_ACTION}\b", rf"\b{_NEW}\s+(?:[\w.\-’']+\s+)?{_TOP_ROLE}\b")
LEADERSHIP_OTHER = _rx(rf"\b{_ACTION}\b{_GAP}\s+{_OTHER_ROLE}\b", rf"\b{_OTHER_ROLE}\b{_GAP}\s+{_ACTION}\b", rf"\b{_NEW}\s+(?:[\w.\-’']+\s+)?{_OTHER_ROLE}\b")

STRATEGIC = _rx(r"\bstrategic\b", r"\bstrategisk", r"\bjoint[- ]venture\b", r"\blong[- ]term\b", r"\blangsiktig", r"\bmulti[- ]year\b", r"\bflerårig", r"\bframework\b", r"\brammeavtale",
                r"\blargest\b", r"\bstørste\b", r"\brecord\b", r"\brekord\b", r"\bfirst[- ]of[- ]its[- ]kind\b", r"\bmajor\b", r"\bsignificant\b", r"\bbetydelig\b", r"\bnew market\b")
OPERATIONAL = _rx(r"\bshut[- ]?down\b", r"\boutage\b", r"\baccident\b", r"\bulykke\b", r"\bfatal", r"\bfire\b", r"\bbrann\b", r"\bexplosion\b", r"\beksplosjon\b", r"\brecall\b", r"\btilbakekall",
                  r"\bhalts?\b", r"\bsuspend", r"\bstans\b", r"\bproduction (?:start|record)\b", r"\bfirst (?:oil|gas)\b", r"\bproduksjonsstart\b")

# --- amounts ---------------------------------------------------------------
_CUR = r"NOK|USD|EUR|GBP|SEK|DKK|CHF|JPY|CAD|AUD|CNY|INR|MNOK|MUSD|MEUR|BNOK|BUSD|BEUR|US\$|kr\.?|kroner|dollars?|euros?|[$€£]"
_MULT = r"billion|bn|b|milliarder|milliard|mrd\.?|million(?:er)?|mill\.?|mn|m|thousand|tusen|k"
_NUM = r"\d{1,3}(?:[  .,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_KNOWN_CODES = {"nok", "usd", "eur", "gbp", "sek", "dkk", "chf", "jpy", "cad", "aud", "cny", "inr"}
AMOUNT_BEFORE = re.compile(rf"(?<![\w$€£])(?P<cur>{_CUR})\s?(?P<num>{_NUM})\s?(?P<mult>{_MULT})?(?![\w])", re.I)
AMOUNT_AFTER = re.compile(rf"(?<![\w.,])(?P<num>{_NUM})\s?(?P<mult>{_MULT})?\s?(?P<cur>NOK|USD|EUR|GBP|SEK|DKK|CHF|kroner|kr|dollars?|euros?)(?![\w])", re.I)
# Only currencies the text itself names unambiguously. "kr"/"kroner" and "$"/"dollar" exist in several currencies, so they carry no code (never guessed).
CURRENCY_WORDS = {"€": "EUR", "euro": "EUR", "euros": "EUR", "£": "GBP", "us$": "USD"}
_ISO_CODE = re.compile(r"^[a-z]{3}$")
_PREFIXED_CODE = re.compile(r"^([mb])([a-z]{3})$")  # MNOK 500 = 500 million, BUSD 2 = 2 billion
MULTIPLIER = {"billion": 1e9, "bn": 1e9, "b": 1e9, "milliarder": 1e9, "milliard": 1e9, "mrd": 1e9, "mrd.": 1e9, "million": 1e6, "millioner": 1e6, "mill": 1e6, "mill.": 1e6, "mn": 1e6, "m": 1e6,
              "thousand": 1e3, "tusen": 1e3, "k": 1e3}
_PREFIX_MULT = {"m": 1e6, "b": 1e9}


def _currency_of(raw: str) -> tuple[str | None, float]:
    """(currency code or None, multiplier implied by the code itself) for the currency wording found next to an amount."""
    low = raw.casefold().rstrip(".")
    if low in CURRENCY_WORDS:
        return CURRENCY_WORDS[low], 1.0
    m = _PREFIXED_CODE.match(low)
    if m and m.group(2) in _KNOWN_CODES:
        return m.group(2).upper(), _PREFIX_MULT[m.group(1)]
    if _ISO_CODE.match(low) and low in _KNOWN_CODES:
        return low.upper(), 1.0
    return None, 1.0


@dataclass(frozen=True)
class Amount:
    value: float
    currency: str | None
    text: str

    def label(self) -> str:
        v = self.value
        body = f"{v / 1e9:.2f} billion" if v >= 1e9 else f"{v / 1e6:.1f} million" if v >= 1e6 else f"{v:,.0f}".replace(",", " ")
        return f"{self.currency} {body}" if self.currency else body


def _number(raw: str) -> float | None:
    """"2,4" → 2.4 · "1 200" → 1200 · "1,200" → 1200 · "1.234.567" → 1234567 · "12.5" → 12.5."""
    s = raw.replace("\u00a0", " ").replace(" ", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) <= 2 and "," not in head else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def find_amounts(text: str) -> list[Amount]:
    """Money amounts written in ``text`` with the currency the text itself states. Nothing is converted; an amount without a stated currency has ``currency=None``."""
    out: list[Amount] = []
    for rx in (AMOUNT_BEFORE, AMOUNT_AFTER):
        for m in rx.finditer(text or ""):
            num = _number(m.group("num"))
            if num is None:
                continue
            code, code_mult = _currency_of(m.group("cur"))
            mult = MULTIPLIER.get((m.group("mult") or "").casefold(), 1.0) * code_mult
            out.append(Amount(num * mult, code, m.group(0).strip()))
    seen: set[tuple[float, str | None]] = set()
    uniq = []
    for a in out:
        if (a.value, a.currency) not in seen:
            seen.add((a.value, a.currency))
            uniq.append(a)
    return uniq


# --- the result -----------------------------------------------------------
@dataclass
class Judgement:
    tier: str
    score: int
    category: str
    reasons: list[str] = field(default_factory=list)
    amount: Amount | None = None


@dataclass
class RevenueContext:
    """The company's latest filed revenue, used only to size an amount stated in the *same* currency."""
    value: float
    currency: str


def classify_text(title: str, description: str | None = None) -> tuple[str, dict[str, bool]]:
    """(category, flags) for an announcement from its wording. Flags: strong, top_role, strategic, operational, routine_marker, weak_only."""
    text = fold(f"{title}. {description or ''}")
    head = fold(title)
    flags = {"strong": False, "top_role": False, "strategic": bool(STRATEGIC.search(text)), "operational": bool(OPERATIONAL.search(text)), "routine_marker": False, "weak_only": False}
    scores: dict[str, float] = {}
    strong: dict[str, bool] = {}
    for cat, rules in PATTERNS.items():
        for rx, weight in rules:
            # the headline counts double: it says what the announcement is about; the summary only supports it
            hit_head, hit_all = rx.search(head), rx.search(text)
            if hit_all:
                scores[cat] = scores.get(cat, 0) + weight * (1.5 if hit_head else 1.0)
                if weight >= 2 and hit_head:
                    strong[cat] = True
    if LEADERSHIP_TOP.search(head) or LEADERSHIP_TOP.search(text[:240]):
        scores["leadership"] = scores.get("leadership", 0) + 3
        strong["leadership"] = True
        flags["top_role"] = True
    elif LEADERSHIP_OTHER.search(head):
        scores["leadership"] = scores.get("leadership", 0) + 1.5
    if AWARD_NOT_CONTRACT.search(text):
        scores.pop("contract", None)
        strong.pop("contract", None)
        scores["announcement"] = scores.get("announcement", 0) + 1
    if ROUTINE_MARKERS.search(head):
        flags["routine_marker"] = True
        for cat in ("results", "regulatory", "contract", "partnership", "location"):  # an invitation to a results presentation is not results
            if cat in scores and not strong.get(cat):
                scores.pop(cat, None)
        if strong.get("results"):
            strong.pop("results", None)
            scores.pop("results", None)
    if not scores:
        return "announcement", {**flags, "weak_only": True}
    best = max(scores, key=lambda c: (scores[c], -PRIORITY.index(c) if c in PRIORITY else -99))
    flags["strong"] = bool(strong.get(best))
    if scores[best] <= 0.75 and not flags["strong"]:  # only ambiguous wording ("kjøper", …): not enough to name the kind of event
        return "announcement", {**flags, "weak_only": True}
    return best, flags


def _age_days(day: str, today: date) -> int:
    try:
        return (today - date.fromisoformat(day)).days
    except ValueError:
        return 10_000


def recency_points(day: str, today: date) -> int:
    age = _age_days(day, today)
    if age <= 30:
        return 12
    if age <= 90:
        return 9
    if age <= 180:
        return 6
    if age <= 365:
        return 3
    if age <= 730:
        return 0
    if age <= 1825:
        return -8
    return -18


def recency_phrase(day: str, today: date) -> str:
    age = _age_days(day, today)
    if age < 0:
        return "dated in the future"
    if age <= 30:
        return "within the last 30 days"
    if age <= 90:
        return "within the last 3 months"
    if age <= 365:
        return "within the last year"
    if age <= 1825:
        return f"about {max(1, round(age / 365))} years ago"
    return "more than 5 years ago"


def _magnitude_points(amount: Amount | None) -> int:
    if amount is None:
        return 0
    v = amount.value
    return 18 if v >= 1e9 else 12 if v >= 1e8 else 6 if v >= 1e7 else 2 if v >= 1e6 else 0


def _relative_points(amount: Amount | None, revenue: RevenueContext | None) -> tuple[int, float | None]:
    """Size against the company's own revenue — only when both are stated in the same currency (never converted)."""
    if amount is None or revenue is None or not amount.currency or amount.currency != revenue.currency or revenue.value <= 0:
        return 0, None
    ratio = amount.value / revenue.value
    pts = 14 if ratio >= 0.10 else 8 if ratio >= 0.01 else 3 if ratio >= 0.001 else 0
    return pts, ratio


SOURCE_POINTS = {"investor_relations": 6, "company_newsroom": 3, "public_procurement": 3, "official_registry": 0, "secondary_news": -4}
SOURCE_PHRASE = {"investor_relations": "the company's investor-relations page", "company_newsroom": "the company's own newsroom", "public_procurement": "an official procurement notice",
                 "official_registry": "an official register", "secondary_news": "news coverage (secondary source)"}


def judge(title: str, description: str | None, day: str, *, source_type: str, today: date, type_hint: str | None = None, amount: Amount | None = None,
          revenue: RevenueContext | None = None, corroborating_types: int = 1) -> Judgement:
    """Judge one (already consolidated) announcement. ``source_type`` is the best source that reported it."""
    category, flags = classify_text(title, description)
    if type_hint in BASE_SCORE and (category == "announcement" or type_hint == "contract"):
        category = type_hint
    amounts = find_amounts(f"{title}. {description or ''}")
    biggest = amount or (max(amounts, key=lambda a: a.value) if amounts else None)
    score = float(BASE_SCORE.get(category, 16))
    reasons: list[str] = []
    category_label = {"acquisition": "Acquisition, merger or divestment", "restructuring": "Restructuring, closure or other material operational change", "results": "Financial results or guidance",
                      "contract": "Contract or order", "discovery": "Discovery or resource update", "funding": "Capital raising or financing", "leadership": "Leadership change",
                      "regulatory": "Regulatory or legal matter", "partnership": "Partnership or agreement", "production": "Production or operations update", "project": "Project milestone",
                      "location": "New or expanded location", "announcement": "General announcement"}.get(category, "Announcement")
    reasons.append(category_label + (" (decisive wording)" if flags["strong"] else ""))
    if flags["strong"]:
        score += 6
    mag = _magnitude_points(biggest)
    rel, ratio = _relative_points(biggest, revenue)
    if biggest is not None and (mag or rel):
        extra = f", about {ratio * 100:.1f}% of last filed revenue in the same currency" if ratio is not None else ""
        reasons.append(f"Stated amount {biggest.label()}{extra}")
    score += max(mag, rel) if rel else mag
    if flags["operational"]:
        score += 8
        reasons.append("Operational consequence (production, outage, safety or recall)")
    if flags["strategic"]:
        score += 6
        reasons.append("Strategic wording (long-term, framework, largest, joint venture…)")
    src = SOURCE_POINTS.get(source_type, 0)
    score += src
    reasons.append(f"Published by {SOURCE_PHRASE.get(source_type, 'a source')}")
    rec = recency_points(day, today)
    score += rec
    reasons.append(f"Dated {day} ({recency_phrase(day, today)})")
    if corroborating_types >= 2:
        score += 4
        reasons.append(f"Reported by {corroborating_types} independent kinds of source")
    if flags["routine_marker"]:
        score -= 24
        reasons.append("Wording of an invitation, event, marketing or notification, not a business development")
    score = max(0, min(100, round(score)))

    material = bool(biggest and (mag >= 6 or rel >= 8)) or flags["strategic"] or source_type == "investor_relations"
    eligible = {
        "acquisition": True, "restructuring": True, "discovery": True, "results": flags["strong"] and not flags["routine_marker"],
        "contract": material, "partnership": flags["strategic"] or bool(biggest and mag >= 6) or (source_type == "investor_relations" and flags["strong"]),
        "leadership": flags["top_role"],
        "funding": flags["strong"] and (bool(biggest and mag >= 6) or source_type == "investor_relations" or bool(MAJOR_FUNDING.search(fold(title)))),
        "production": flags["strong"], "project": flags["strong"], "regulatory": flags["strong"],
    }.get(category, False)
    if category == "contract" and not material:
        reasons.append("No stated size or strategic wording, so not treated as a major contract")
    if category in ("leadership",) and not flags["top_role"]:
        reasons.append("Not a top-level role (CEO, CFO, chair, president…)")
    if flags["routine_marker"]:
        tier = ROUTINE
    elif eligible and score >= MAJOR_MIN_SCORE:
        tier = MAJOR
    elif score >= RELEVANT_MIN_SCORE:
        tier = RELEVANT
    else:
        tier = ROUTINE
    if category == "announcement" and PRODUCT_LAUNCH.search(fold(title)) and tier == ROUTINE and not flags["routine_marker"]:
        score = max(score, 38) if recency_points(day, today) >= 0 else score
        tier = RELEVANT if score >= RELEVANT_MIN_SCORE else ROUTINE
        reasons.insert(1, "Product or service launch")
    return Judgement(tier=tier, score=score, category=category, reasons=reasons, amount=biggest)


# --- registry events --------------------------------------------------------
REGISTRY_BASE = {"registration": 4, "founded": 2, "establishment": 8, "subsidiary": 16, "name_change": 38, "group": 40, "procurement_buyer": 14}
REGISTRY_REASON = {
    "registration": "Registry bookkeeping: the date the company was entered in Enhetsregisteret",
    "founded": "Registry bookkeeping: the company's founding date",
    "establishment": "Registry bookkeeping: an establishment (underenhet) was registered; this does not by itself mean a business expansion",
    "subsidiary": "Registry record: a subsidiary appears in the group structure",
    "name_change": "Registry record: a former registered name",
    "group": "Registry record: the company is recorded as part of a group",
    "procurement_buyer": "Official procurement notice published by the company as the buyer: routine purchasing, not an announcement about the company's own business",
}


def judge_registry(kind: str, day: str, *, today: date) -> Judgement:
    """Register entries are kept, but never count as major business developments."""
    score = REGISTRY_BASE.get(kind, 4) + recency_points(day, today)
    score = max(0, min(REGISTRY_SCORE_CAP, score))
    tier = RELEVANT if score >= RELEVANT_MIN_SCORE else ROUTINE
    category = {"establishment": "location", "group": "registration", "subsidiary": "registration", "name_change": "registration"}.get(kind, "registration")
    return Judgement(tier=tier, score=score, category=category, reasons=[REGISTRY_REASON.get(kind, "Registry record"), f"Dated {day} ({recency_phrase(day, today)})",
                                                                      "Register entries stay available but are not counted as major business developments"])
