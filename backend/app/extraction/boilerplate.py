"""Page furniture is not evidence: navigation menus, cookie/consent banners, skip-links and footer text.

A site's menu ("Hjem Om oss Tjenester Karriere Kontakt Personvern …") can be scraped as a "paragraph" and then looks like a sentence about the
company. ``is_boilerplate`` recognises it from the text alone (no site-specific rules), so it can be applied wherever page text becomes a fact,
a headline or an answer.
"""
from __future__ import annotations

import re

_COOKIE = re.compile(
    r"(cookie|informasjonskapsler|samtykke til|vi bruker (cookies|informasjonskapsler)|we use cookies|accept all|godta alle|avvis alle|manage preferences|"
    r"personvernerklæring|privacy (policy|notice|statement)|terms (of use|and conditions)|brukervilkår|all rights reserved|alle rettigheter|©)",
    re.I,
)
_SKIP = re.compile(r"(skip to (main )?content|hopp til (hoved)?innhold|gå til (hoved)?innhold|til hovedinnhold|back to top|til toppen)", re.I)
# Menu / header / footer vocabulary in Norwegian and English. Matched as whole words or phrases.
_NAV_TERMS = (
    "hjem", "home", "om oss", "om selskapet", "about us", "about", "kontakt oss", "kontakt", "contact us", "contact", "tjenester", "services", "produkter", "products",
    "løsninger", "solutions", "karriere", "careers", "career", "ledige stillinger", "jobs", "nyheter", "news", "presse", "press", "media", "pressemeldinger", "investor",
    "investors", "investorrelasjoner", "bærekraft", "sustainability", "personvern", "privacy", "cookies", "meny", "menu", "søk", "search", "logg inn", "log in", "login",
    "språk", "language", "norsk", "english", "svenska", "handlekurv", "cart", "følg oss", "follow us", "facebook", "linkedin", "instagram", "youtube", "twitter", "x",
    "sitemap", "nettkart", "les mer", "read more", "se mer", "see more", "prosjekter", "projects", "referanser", "references", "kunder", "customers", "partnere",
    "partners", "team", "ansatte", "våre", "ofte stilte spørsmål", "faq", "varslingskanal", "whistleblowing", "tilgjengelighetserklæring",
)
_NAV_RX = re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in sorted(_NAV_TERMS, key=len, reverse=True)) + r")(?!\w)", re.I)
_SEPARATORS = re.compile(r"[|»›•·/>]{1}")
_SENTENCE_END = re.compile(r"[.!?…]\s|[.!?…]$")


def nav_term_count(text: str) -> int:
    return len(_NAV_RX.findall(text))


def is_boilerplate(text: str | None) -> bool:
    """True for navigation menus, cookie/consent text, skip-links and footer legalese. Ordinary sentences and headlines are never flagged."""
    t = (text or "").strip()
    if not t:
        return True
    if _SKIP.search(t) and len(t) < 400:
        return True
    cookie = _COOKIE.search(t)
    words = re.findall(r"[^\W\d_]+", t)
    if cookie and len(t) < 600:
        return True
    hits = nav_term_count(t)
    if len(words) <= 1:
        return False
    sentences = len(_SENTENCE_END.findall(t))
    # A run of menu words with no sentence structure: "Hjem Om oss Tjenester Karriere Kontakt …"
    density = hits / len(words)
    if hits >= 4 and ((density >= 0.4 and sentences == 0) or (density >= 0.6 and sentences <= 1)):
        return True
    if hits >= 3 and density >= 0.5 and sentences == 0:
        return True
    separators = len(_SEPARATORS.findall(t))
    if separators >= 3 and hits >= 2 and density >= 0.3 and sentences == 0:
        return True
    return False


def strip_boilerplate(paragraphs: list[str]) -> list[str]:
    return [p for p in paragraphs if not is_boilerplate(p)]
