"""Which article candidates are fetched first, and which are the same article.

Every article page costs a request from a small per-company allowance, so the order matters. Listing cards, JSON-LD and feed items are only *candidates*; before any of
them is requested they are

* merged when they are the same article (the same address written differently, or the same headline and date under two addresses), and
* ordered by how likely the address and headline are to be an actual news article rather than an event page, a conference or webcast page, a calendar entry or a
  generic listing page. Nothing is excluded by this: a lower-ranked candidate is still fetched when the allowance lasts, it just never takes a request from a better one.
  A candidate is published only after its own page passes every check in ``news_article.py`` / ``news_validation.py``, whatever its rank.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from ..core.util import fold
from ..identity.normalization import normalize_name
from ..security.urls import canonical_url
from . import news_validation as nv

NEWS_SECTIONS = {"news", "nyheter", "press", "presse", "pressemeldinger", "pressemelding", "pressroom", "newsroom", "news-and-media", "stories", "story", "magazine", "blog",
                 "blogg", "aktuelt", "artikler", "articles", "pressreleases", "press-releases"}
DATED_SLUG = re.compile(r"(?:^|/)(?:20\d{6}|20\d{2}[-/]\d{2}[-/]\d{2})(?:[-_/]|$)")
EVENT_URL = re.compile(r"(?:^|[-_/])(?:analyst-conference|press-conference|conference|webcast|webinar|seminar|capital-markets-day|investor-day|supplier-day|annual-general-meeting|"
                       r"general-meeting|agm|events?|calendar|kalender|konferanse|generalforsamling|arrangement|presentation|presentasjon)(?:$|[-_/0-9])", re.I)
EVENT_TITLE = re.compile(r"\b(?:conference|webcast|webinar|seminar|supplier day|capital markets day|investor day|annual general meeting|general meeting|konferanse|"
                         r"generalforsamling|arrangement|calendar|kalender|events?)\b", re.I)
LEGAL_WORDS = {"as", "asa", "a", "s"}


def _company_words(legal_name: str | None) -> set[str]:
    return set(normalize_name(legal_name or "").split()) | LEGAL_WORDS


def _headline_words(title: str, legal_name: str | None) -> list[str]:
    drop = _company_words(legal_name)
    return [w for w in re.findall(r"\w+", fold(title)) if w not in drop]


def score(cand: Any, legal_name: str | None) -> int:
    """Higher = more likely to be a news article. > 0 likely article · 0 unknown · < 0 likely an event page, a listing or a notice without a headline."""
    url = cand.url or ""
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower()
    segments = [s for s in path.split("/") if s]
    points = 0
    dated = bool(DATED_SLUG.search(path))
    if dated:
        points += 2
    elif len(segments) >= 2 and segments[-1] not in NEWS_SECTIONS and any(s in NEWS_SECTIONS for s in segments[:-1]) and (segments[-1].count("-") >= 2 or len(segments[-1]) >= 16):
        points += 1
    if any(f.get("kind") in ("rss_item", "json_ld") for f in cand.found_in):
        points += 1  # a feed item or structured article data declares itself an article
    penalty = 0
    if EVENT_URL.search(path):
        penalty = 2 if dated else 3  # a dated news address that mentions an event is an announcement about it; an undated event address is the event page
    elif EVENT_TITLE.search(cand.title or ""):
        penalty = 2
    last = segments[-1] if segments else ""
    title_folded = fold(cand.title or "").strip(" .:|-")
    if last in nv.SECTION_SEGMENTS | nv.NON_ARTICLE_SEGMENTS or title_folded in nv.NAV_TITLES or nv.NAV_PATTERN.match(title_folded):
        penalty = max(penalty, 3)  # a generic listing / navigation page
    points -= penalty
    if len(_headline_words(cand.title or "", legal_name)) < 3:
        points -= 1  # "Notifiable trading": barely a headline
    return points


def tier(points: int) -> int:
    return 1 if points >= 1 else (0 if points == 0 else -1)


def _address_key(url: str) -> str:
    parts = urllib.parse.urlsplit(canonical_url(url))
    host = (parts.hostname or "").removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}" + (f"?{parts.query}" if parts.query else "")


def _headline_key(cand: Any, legal_name: str | None) -> str:
    return " ".join(_headline_words(cand.title or "", legal_name))


def merge_equivalents(candidates: list[Any], legal_name: str | None) -> tuple[list[Any], int]:
    """(candidates with equivalent ones merged, how many were merged away). Equivalent = the same address (scheme, ``www``, trailing slash and tracking parameters
    ignored) or the same headline with the same date under different addresses. The better-ranked one is kept; what the others were found in and their dates are kept with it."""
    kept: list[Any] = []
    by_address: dict[str, Any] = {}
    by_headline: dict[tuple[str, str], Any] = {}
    merged = 0
    for cand in candidates:
        if not cand.url:
            kept.append(cand)
            continue
        akey = _address_key(cand.url)
        hkey = _headline_key(cand, legal_name)
        twin = by_address.get(akey) or (by_headline.get((hkey, cand.hint_date or "")) if len(hkey) >= 12 else None)
        if twin is None:
            kept.append(cand)
            by_address[akey] = cand
            if len(hkey) >= 12:
                by_headline[(hkey, cand.hint_date or "")] = cand
            continue
        merged += 1
        better, other = (cand, twin) if score(cand, legal_name) > score(twin, legal_name) else (twin, cand)
        better.found_in.extend(f for f in other.found_in if f not in better.found_in)
        better.listing_date = better.listing_date or other.listing_date
        if other.feed_date and not better.feed_date:
            better.feed_date, better.feed_date_source = other.feed_date, other.feed_date_source
        better.summary = better.summary or other.summary
        if better is cand:  # the newcomer ranks higher: it takes the twin's place
            kept[kept.index(twin)] = cand
        by_address[akey] = better
        by_address[_address_key(other.url)] = better
        if len(hkey) >= 12:
            by_headline[(hkey, cand.hint_date or "")] = better
    return kept, merged


def order(candidates: list[Any], legal_name: str | None) -> list[Any]:
    """Likely articles first, then unknown, then likely event/listing pages; within each, the newest first (a feed item before a card of the same date)."""
    return sorted(candidates, key=lambda c: (tier(score(c, legal_name)), c.hint_date or "", bool(c.feed_date)), reverse=True)
