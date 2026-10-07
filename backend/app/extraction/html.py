"""Deterministic HTML parsing: text, metadata, links, contact details, JSON-LD.

The LLM never sees raw HTML. Pages are reduced to a ``PageDoc`` first; only
targeted text excerpts are ever sent to a model.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from ..core.util import clean_ws
from ..security.urls import canonical_url, host_of, registrable_domain

PAGE_KINDS: dict[str, tuple[str, ...]] = {
    "about": ("om-oss", "om oss", "about", "om-selskapet", "selskapet", "hvem-er-vi", "hvem vi er", "who-we-are", "company", "virksomheten", "historie", "history"),
    "contact": ("kontakt", "contact", "finn-oss", "find-us", "kontakt-oss", "kundeservice"),
    "careers": ("karriere", "career", "jobb", "jobs", "stilling", "ledige", "vacanc", "work-with-us", "jobbe-hos", "join-us", "rekruttering", "recruit"),
    "news": ("nyheter", "news", "aktuelt", "presse", "press", "blogg", "blog", "artikler", "media", "nyhet"),
    "investors": ("investor", "ir", "finansiell-informasjon", "aksjonær", "shareholder"),
    "sustainability": ("baerekraft", "bærekraft", "sustainability", "esg", "miljø", "miljo", "csr", "samfunnsansvar"),
    "team": ("ansatte", "team", "ledelse", "ledelsen", "management", "people", "medarbeidere", "styret", "board", "våre-ansatte", "folkene"),
    "products": ("produkter", "products", "tjenester", "services", "løsninger", "losninger", "solutions", "tilbud", "what-we-do", "hva-vi-gjor"),
    "locations": ("avdelinger", "kontorer", "offices", "locations", "lokasjoner", "butikker", "stores", "våre-kontorer"),
}

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin", "facebook.com": "facebook", "fb.com": "facebook", "instagram.com": "instagram", "twitter.com": "x", "x.com": "x",
    "youtube.com": "youtube", "youtu.be": "youtube", "github.com": "github", "tiktok.com": "tiktok",
}

ATS_HOSTS = (
    "teamtailor.com", "webcruiter.no", "webcruiter.com", "jobylon.com", "recman.no", "recman.page", "hrmanager.no", "easycruit.com", "reachmee.com",
    "jobbnorge.no", "myworkdayjobs.com", "lever.co", "greenhouse.io", "smartrecruiters.com", "recruitee.com", "personio.de", "personio.com",
    "varbi.com", "emply.com", "talentech.com", "homerun.co", "workable.com", "breezy.hr", "jobs.ashbyhq.com", "arbeidsplassen.nav.no",
)

PARKED_MARKERS = (
    "domain is for sale", "domenet er til salgs", "this domain may be for sale", "buy this domain", "parked free", "parkert",
    "denne siden er under konstruksjon", "under construction", "coming soon", "kommer snart", "website is coming", "site not found",
    "default web site page", "welcome to nginx", "apache2 ubuntu default page", "it works!", "domeneshop", "one.com - ", "webhuset",
    "this site can’t be reached", "account suspended", "hosting by", "godaddy", "sedo domain parking", "dan.com",
)


@dataclass
class Link:
    url: str
    text: str


@dataclass
class TimeItem:
    datetime: str
    text: str
    context: str


@dataclass
class PageDoc:
    url: str
    final_url: str
    title: str = ""
    description: str = ""
    og: dict[str, str] = field(default_factory=dict)
    lang: str = ""
    canonical: str = ""
    text: str = ""
    paragraphs: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    times: list[TimeItem] = field(default_factory=list)
    footer_text: str = ""
    content_sha256: str | None = None
    retrieved_at: str | None = None

    @property
    def domain(self) -> str:
        return registrable_domain(host_of(self.final_url or self.url))


def _flatten_jsonld(value: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(value, list):
        for item in value:
            _flatten_jsonld(item, out)
    elif isinstance(value, dict):
        if "@graph" in value:
            _flatten_jsonld(value["@graph"], out)
        if "@type" in value:
            out.append(value)
        for key in ("mainEntity", "itemListElement", "publisher", "author", "hiringOrganization"):
            if isinstance(value.get(key), (dict, list)) and key != "publisher":
                _flatten_jsonld(value[key], out)


def parse_html(url: str, final_url: str, html: str, *, content_sha256: str | None = None, retrieved_at: str | None = None) -> PageDoc:
    soup = BeautifulSoup(html or "", "lxml")
    doc = PageDoc(url=url, final_url=final_url or url, content_sha256=content_sha256, retrieved_at=retrieved_at)
    if soup.title and soup.title.string:
        doc.title = clean_ws(soup.title.string)[:300]
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        doc.lang = str(html_tag.get("lang"))[:10]
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        content = clean_ws(meta.get("content") or "")
        if not content:
            continue
        if name == "description":
            doc.description = content[:600]
        elif name.startswith("og:"):
            doc.og[name[3:]] = content[:600]
    canon = soup.find("link", rel=lambda v: v and "canonical" in v)
    if canon and canon.get("href"):
        doc.canonical = urllib.parse.urljoin(doc.final_url, canon["href"])

    for script in soup.find_all("script", type=lambda v: v and "ld+json" in v):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        _flatten_jsonld(data, doc.jsonld)

    base = doc.final_url
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        text = clean_ws(a.get_text(" "))[:160]
        if href.startswith("mailto:"):
            email = urllib.parse.unquote(href[7:].split("?")[0]).strip().lower()
            if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email) and email not in doc.emails:
                doc.emails.append(email)
            continue
        if href.startswith("tel:"):
            tel = re.sub(r"[^\d+]", "", href[4:])
            if tel and tel not in doc.phones:
                doc.phones.append(tel)
            continue
        if href.startswith(("javascript:", "#")):
            continue
        absolute = urllib.parse.urljoin(base, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        key = canonical_url(absolute)
        if key in seen:
            continue
        seen.add(key)
        doc.links.append(Link(absolute, text))

    for t in soup.find_all("time"):
        dt = t.get("datetime") or ""
        if dt:
            parent = t.find_parent(["article", "li", "div", "section"]) or t.parent
            context = clean_ws(parent.get_text(" ") if parent else t.get_text(" "))[:300]
            doc.times.append(TimeItem(str(dt), clean_ws(t.get_text(" ")), context))

    footer = soup.find("footer")
    if footer:
        doc.footer_text = clean_ws(footer.get_text(" "))[:3000]
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        tag.decompose()
    doc.headings = [clean_ws(h.get_text(" "))[:200] for h in soup.find_all(["h1", "h2", "h3"]) if clean_ws(h.get_text(" "))][:40]
    paragraphs = []
    for p in soup.find_all(["p", "li"]):
        text = clean_ws(p.get_text(" "))
        if 60 <= len(text) <= 1200 and not text.lower().startswith(("cookie", "vi bruker informasjonskapsler", "we use cookies")):
            paragraphs.append(text)
    doc.paragraphs = paragraphs[:80]
    doc.text = clean_ws(soup.get_text(" "))[:60000]
    return doc


def classify_link(url: str, text: str = "") -> str | None:
    """Classify a same-site link by its path segments and anchor text (word-level, not substring soup)."""
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path.lower())
    tokens = [t for t in re.split(r"[/\-_.]+", path) if t]
    words = set(re.findall(r"[\wæøå]+", (text or "").lower()))
    for kind, needles in PAGE_KINDS.items():
        for needle in needles:
            if " " in needle or "-" in needle:
                hyphen = needle.replace(" ", "-")
                if hyphen in path or (needle.replace("-", " ") in (text or "").lower()):
                    return kind
                continue
            if any(t == needle or (len(needle) >= 4 and t.startswith(needle)) for t in tokens):
                return kind
            if len(needle) >= 4 and any(w == needle or w.startswith(needle) for w in words):
                return kind
    return None


def social_profile(url: str) -> tuple[str, str] | None:
    host = host_of(url).removeprefix("www.").removeprefix("m.").removeprefix("no.")
    network = SOCIAL_HOSTS.get(host) or next((v for k, v in SOCIAL_HOSTS.items() if host.endswith("." + k)), None)
    if not network:
        return None
    path = urllib.parse.urlsplit(url).path.strip("/")
    if not path or path.split("/")[0] in ("sharer", "share", "intent", "sharer.php", "shareArticle", "plugins", "dialog", "watch", "embed", "hashtag", "search", "login"):
        return None
    if network == "linkedin" and not path.startswith(("company/", "school/", "showcase/")):
        return None  # personal profiles are not company profiles
    if network == "youtube" and not path.startswith(("channel/", "c/", "user/", "@")):
        return None
    handle = path.split("/")[1] if network == "linkedin" and "/" in path else path.split("/")[0]
    return network, handle


def is_ats(url: str) -> bool:
    host = host_of(url)
    return any(host == h or host.endswith("." + h) for h in ATS_HOSTS)


def looks_parked(doc: PageDoc) -> bool:
    sample = (doc.title + " " + doc.text[:2500]).lower()
    if len(doc.text) < 120 and not doc.jsonld:
        return True
    return any(marker in sample for marker in PARKED_MARKERS) and len(doc.text) < 3000


def jsonld_of_type(doc: PageDoc, *types: str) -> list[dict[str, Any]]:
    wanted = {t.lower() for t in types}
    out = []
    for item in doc.jsonld:
        kind = item.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(str(k).lower() in wanted for k in kinds if k):
            out.append(item)
    return out


def text_contains(haystack: str, needle: str) -> bool:
    """Whitespace/case-insensitive containment — used to verify quoted evidence."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip().casefold()  # noqa: E731
    n = norm(needle)
    return bool(n) and n in norm(haystack)


def find_span(text: str, needle: str, radius: int = 120) -> str:
    """Return an excerpt of ``text`` around ``needle`` (exact page wording)."""
    idx = text.casefold().find(needle.casefold())
    if idx < 0:
        return needle
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")
