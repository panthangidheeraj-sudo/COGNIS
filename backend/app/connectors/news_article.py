"""Stage B of news verification: what a fetched page must show before it is a published, dated article about THIS legal entity.

A newsroom card, a feed item or a search hit only tells COGNIS where to look. The page the link points to is fetched and judged here:

* ``read_article``      is it one article — a headline that is really on the page, and a publication date that the page itself states as such;
* ``publication_date``  the date and *where it came from*: JSON-LD ``datePublished``, ``article:published_time`` or an article-scoped
                        ``<time itemprop="datePublished">``. ``dateModified``, ``dateCreated``, generic ``<time datetime>`` elements, listing-card dates, feed-build
                        dates and the retrieval date never count (a feed item's own ``pubDate`` / Atom ``published`` is handled by the newsroom connector);
* ``entity_basis``      does the article name the exact registered legal entity: its organisation number in the article text, or its exact registered name in
                        the headline or body. A parent group, a sister company, a longer name ("Autobjørn Bergen AS") or a shared brand word is not enough, and a
                        page that carries a different organisation number is rejected.

Everything here reads a ``PageDoc`` only; no request is made.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core.util import clean_ws, date_only, truncate
from ..extraction.html import PageDoc, jsonld_of_type
from ..identity.employer import org_numbers_in
from ..identity.model import CanonicalIdentity
from ..identity.normalization import continues_into_longer_name, is_generic_name, name_in_text, normalize_name

ARTICLE_TYPES = ("NewsArticle", "Article", "ReportageNewsArticle", "AnalysisNewsArticle", "BlogPosting", "PressRelease")
EXCERPT_CHARS = 300
BOILERPLATE = re.compile(r"(cookie|personvern|privacy|javascript|abonnement|subscribe|logg inn|log in|©|all rights reserved)", re.I)
_LEGAL_FORM = r"(?:A\s*/\s*S|AS|ASA)"
_NAME_WORD = r"[A-ZÆØÅ][\wæøåÆØÅ'’-]*"


@dataclass
class Article:
    headline: str
    day: str  # ISO publication date; "" when the page states none (see ``date_why``)
    lead: str
    nosnippet: bool = False
    date_source: str | None = None  # datePublished | published_time | time_itemprop_datePublished
    date_why: str | None = None  # why there is no publication date
    paragraphs: list[str] = field(default_factory=list)  # article text, page furniture (menus, footers, dialogs) excluded


def _norm(text: str) -> str:
    from ..core.util import fold

    return re.sub(r"[^\w]+", " ", fold(text)).strip()


def _strip_site_name(title: str) -> str:
    """"Headline | E24" → "Headline" (only when what remains is still a headline)."""
    for sep in (" | ", " – ", " — ", " - "):
        head, _, tail = title.rpartition(sep)
        if head and len(head) >= 12 and len(tail) <= 32:
            return head.strip()
    return title


def _article_url(art: dict[str, Any]) -> str:
    main = art.get("mainEntityOfPage")
    return str(art.get("url") or (main.get("@id") if isinstance(main, dict) else main) or "")


def publication_date(doc: PageDoc, chosen: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:
    """(ISO day, source, None) when the page states a publication date, else (None, None, reason). Only demonstrable publication dates are used."""
    day = date_only(str((chosen or {}).get("datePublished") or ""))
    if day:
        return day, "datePublished", None
    day = date_only(doc.meta_dates.get("published_time"))
    if day:
        return day, "published_time", None
    explicit = {d for d in (date_only(t.datetime) for t in doc.pub_times) if d}
    if len(explicit) == 1:
        return next(iter(explicit)), "time_itemprop_datePublished", None
    if len(explicit) > 1:
        return None, None, "the page states several publication dates, so it lists more than one article"
    only_modified = bool((chosen or {}).get("dateModified") or (chosen or {}).get("dateCreated") or doc.meta_dates.get("modified_time") or doc.meta_dates.get("time_modified"))
    if only_modified:
        return None, None, "the page states only a modification date, not a publication date"
    if doc.times:
        return None, None, "the page states no publication date (its only date is a generic <time> element, which does not say when the article was published)"
    return None, None, "the page states no publication date"


def read_article(doc: PageDoc, *, require_date: bool = True) -> tuple[Article | None, str | None]:
    """The article a page is, or why it is not one: (article, None) | (None, reason). Reads the page only; nothing is guessed.

    ``require_date=False`` returns the article even when no publication date can be read (``Article.day == ""``, ``date_why`` says why) so that a caller can
    judge the other rules first and report the first one that fails."""
    ld = jsonld_of_type(doc, *ARTICLE_TYPES)
    chosen: dict[str, Any] | None = None
    if len(ld) == 1:
        chosen = ld[0]
    elif len(ld) > 1:
        here = {u.rstrip("/") for u in (doc.final_url, doc.canonical) if u}
        chosen = next((a for a in ld if _article_url(a).rstrip("/") in here), None)
        if chosen is None:
            return None, "the page lists several articles (a section page), not one article"
    candidates = [clean_ws(str((chosen or {}).get("headline") or (chosen or {}).get("name") or "")), clean_ws(doc.og.get("title", "")),
                  clean_ws(doc.headings[0]) if doc.headings else "", clean_ws(doc.title)]
    surface = _norm(" ".join([doc.title, doc.og.get("title", ""), *doc.headings[:6], doc.text[:6000]]))
    headline = next((h for h in (_strip_site_name(c) for c in candidates) if len(h) >= 12 and _norm(h)[:48] in surface), "")
    if not headline:
        return None, "no headline could be read from the page"
    day, source, why = publication_date(doc, chosen)
    if day is None and require_date:
        return None, why
    lead = next((p for p in doc.paragraphs if len(p) >= 60 and not BOILERPLATE.search(p) and _norm(p)[:40] != _norm(headline)[:40]), "")
    nosnippet = any(flag in doc.robots_meta for flag in ("nosnippet", "noarchive", "none"))
    return Article(headline=truncate(headline, 220), day=day or "", lead="" if nosnippet else truncate(lead, EXCERPT_CHARS), nosnippet=nosnippet, date_source=source,
                   date_why=why, paragraphs=list(doc.paragraphs)), None


# ------------------------------------------------------------------------------- identity --
def _core_pattern(legal_name: str) -> str:
    return r"\s+".join(re.escape(w) for w in normalize_name(legal_name).split())


def _named_exactly(text: str, legal_name: str) -> bool:
    """The exact registered name with its legal form ("Autobjørn AS" / "AUTOBJØRN A/S") occurs in a sentence where it is not the start or end of a longer company
    name. Sentences are judged one at a time, so the last word of the previous sentence is never read as part of the name."""
    core = _core_pattern(legal_name)
    if not core or not text:
        return False
    pattern = re.compile(rf"(?<!\w)(?i:{core})\s+(?i:{_LEGAL_FORM})(?!\w)")
    return any(pattern.search(sentence) and not continues_into_longer_name(sentence, legal_name) for sentence in re.split(r"(?<=[.!?])\s+", text))


def _named_in_headline(headline: str, legal_name: str) -> bool:
    """The name (suffix-insensitive) is in the headline and is not obviously the beginning of a longer name ("Autobjørn Gruppen …", "Autobjørn Bergen AS …")."""
    if not name_in_text(legal_name, headline) or continues_into_longer_name(headline, legal_name):
        return False
    core = _core_pattern(legal_name)
    return not re.search(rf"(?<!\w)(?i:{core})\s+(?!{_LEGAL_FORM}(?!\w)){_NAME_WORD}", headline)


def entity_basis(doc: PageDoc, article: Article, identity: CanonicalIdentity, related: list[dict] | None = None) -> tuple[str | None, str | None, dict[str, Any]]:
    """How the article is tied to this exact legal entity: (basis, None, details) or (None, reason, details). A similar name proves nothing."""
    ours = identity.org_number
    legal = re.sub(r"\ba\s*/\s*s\b", "AS", identity.legal_name or "", flags=re.I)
    page_numbers = org_numbers_in([doc.text])
    body = " ".join(article.paragraphs)
    body_numbers = org_numbers_in([body])
    others = sorted(page_numbers - {ours})
    details: dict[str, Any] = {"organisation_numbers_on_page": sorted(page_numbers)}
    name_ok = bool(legal) and not is_generic_name(legal) and len(normalize_name(legal)) >= 5
    in_headline = name_ok and _named_in_headline(article.headline, legal)
    in_body = name_ok and _named_exactly(f"{article.headline}. {body}", legal)

    if others and ours not in page_numbers:
        return None, f"the page states a different organisation number ({others[0]}), so it is not about this legal entity", details
    if others:  # several organisations on one page: the page is not automatically about all of them
        if in_headline:
            return "exact_legal_name_in_headline", None, details
        return None, "the page lists several organisation numbers and its headline does not name this legal entity", details
    if ours in body_numbers:
        return "organisation_number_in_article", None, details
    if in_headline:
        return "exact_legal_name_in_headline", None, details
    if in_body:
        return "exact_legal_name_in_article_text", None, details
    for rel in related or []:
        rname = str(rel.get("name") or "")
        if rname and name_in_text(rname, f"{article.headline} {body}"):
            return None, f"the article is about the parent group ({rname}), not this legal entity", details
    if name_ok and name_in_text(legal, f"{article.headline} {body}"):
        return None, "the article uses a name that continues into, or could belong to, another company (a similar name is not enough)", details
    if ours in page_numbers:
        return None, "only the site footer carries the organisation number; the article itself does not name this legal entity", details
    return None, "the article does not name this exact legal entity (its organisation number or registered name) in its headline or text", details
