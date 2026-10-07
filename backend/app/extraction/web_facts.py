"""Verified company website → candidate observations (deterministic).

Nothing here runs unless the identity gate verified the site as belonging to
the exact organisation number. Every observation carries the exact page
wording (``claim_span``), the page URL, retrieval time and content hash.
Search results never reach this module.
"""
from __future__ import annotations

import re
from typing import Any

from ..connectors.jobs import JobItem
from ..connectors.website import SiteCrawl
from ..core.util import clean_ws, date_only, parse_iso, truncate
from ..evidence.models import Observation
from ..identity.normalization import email_domain, normalize_phone
from .html import PageDoc, find_span, jsonld_of_type

WEBSITE_SOURCE_NAME = "Official company website"
NEWS_TITLE_MIN = 12


def _page_base(crawl: SiteCrawl, doc: PageDoc, *, tier: str = "B") -> dict[str, Any]:
    return {
        "module": "website", "source_id": "website", "source_name": f"{WEBSITE_SOURCE_NAME} ({crawl.domain})", "source_class": crawl.source_class,
        "source_url": doc.final_url, "retrieved_at": doc.retrieved_at, "content_sha256": doc.content_sha256, "tier": tier,
        "identity_score": crawl.audit.score if crawl.audit else 0.0, "identity_signals": list(crawl.audit.signals) if crawl.audit else [],
    }


def _lang(doc: PageDoc) -> str | None:
    lang = (doc.lang or "").lower()
    if lang.startswith(("nb", "nn", "no")):
        return "no"
    if lang.startswith("en"):
        return "en"
    return None


def website_observations(crawl: SiteCrawl) -> list[Observation]:
    """Website identity, title/description, contact details, social profiles, pages."""
    if not crawl.verified or crawl.homepage is None or crawl.audit is None:
        return []
    home = crawl.homepage
    obs: list[Observation] = []
    audit = crawl.audit
    best_signal = next((s for s in ("org_number_on_site", "norid_holder_match", "registered_email_on_site", "registered_address_on_site", "legal_name_on_site",
                                     "registered_phone_on_site", "registry_listed_website") if s in audit.evidence), None)
    span = audit.evidence.get(best_signal or "", "") or f"identity signals: {', '.join(audit.signals)}"
    evidence_doc = next((d for d in crawl.docs() if best_signal and audit.evidence.get(best_signal, "")[:40] and audit.evidence[best_signal][:40] in (d.text + d.footer_text)), home)
    obs.append(Observation(
        field="official_website", value=home.final_url.rstrip("/"), claim_span=truncate(span, 300), extraction_method="identity_gate",
        label="Official website", attributes={"domain": crawl.domain, "signals": audit.signals, "score": round(audit.score, 2), "origin": crawl.origin},
        excerpt_language=_lang(evidence_doc), document_title=evidence_doc.title or None, **{**_page_base(crawl, evidence_doc), "tier": "A" if crawl.origin == "registry" else "B"},
    ))
    if home.title:
        obs.append(Observation(field="website_title", value=home.title, claim_span=f"<title>{truncate(home.title, 280)}</title>", extraction_method="html_meta",
                               label="Website title", document_title=home.title, excerpt_language=_lang(home), **_page_base(crawl, home)))
    description = home.description or home.og.get("description")
    if description and len(description) >= 25:
        obs.append(Observation(field="website_description", value=description, claim_span=f'<meta name="description" content="{truncate(description, 260)}">',
                               extraction_method="html_meta", label="Website description", document_title=home.title or None, excerpt_language=_lang(home),
                               **_page_base(crawl, home)))

    # Social profiles linked from the verified site (company pages only; personal profiles are never collected).
    for prof in sorted(crawl.social, key=lambda s: (s["network"], s["url"])):
        page = next((d for d in crawl.docs() if d.final_url == prof.get("page")), home)
        obs.append(Observation(field=f"social_profile_{prof['network']}", value=prof["url"], key_suffix=prof["url"],
                               claim_span=f'link on {page.final_url}: {prof["url"]}', extraction_method="company_linked_profile",
                               label=f"{prof['network'].title() if prof['network'] != 'x' else 'X'} profile", attributes={"network": prof["network"], "handle": prof.get("handle")},
                               **{**_page_base(crawl, page), "source_class": "company_linked_social_profile"}))

    # Contact details: e-mail on the company's own domain, phone numbers on the contact page.
    contact_docs = crawl.docs("contact") or [home]
    seen_mail: set[str] = set()
    for doc in contact_docs + [home]:
        for email in doc.emails:
            if email in seen_mail or email_domain(email) != crawl.domain:
                continue
            seen_mail.add(email)
            obs.append(Observation(field="contact_email", value=email, key_suffix=email, claim_span=f"mailto:{email} on {doc.final_url}", extraction_method="html_link",
                                   label="Contact e-mail", **_page_base(crawl, doc)))
            if len(seen_mail) >= 3:
                break
    seen_phone: set[str] = set()
    for doc in contact_docs:
        for tel in doc.phones[:3]:
            norm = normalize_phone(tel)
            if not norm or norm in seen_phone:
                continue
            seen_phone.add(norm)
            obs.append(Observation(field="contact_phone", value=tel, key_suffix=norm, claim_span=f"tel:{tel} on {doc.final_url}", extraction_method="html_link",
                                   label="Contact phone", **_page_base(crawl, doc)))

    # Pages that exist on the verified site.
    for page in crawl.pages:
        if page.kind == "home" or page.doc is None:
            continue
        if page.kind in ("careers", "news", "investors", "sustainability", "about", "contact", "products", "team", "locations"):
            obs.append(Observation(field=f"{page.kind}_page", value=page.doc.final_url, claim_span=f"{page.kind} page reached from the homepage: {page.doc.title or page.doc.final_url}",
                                   extraction_method="site_navigation", label=f"{page.kind.title()} page", document_title=page.doc.title or None,
                                   **_page_base(crawl, page.doc)))

    obs.extend(jsonld_organization_observations(crawl))
    return obs


def jsonld_organization_observations(crawl: SiteCrawl) -> list[Observation]:
    """Company-reported Organization structured data (secondary; never overrides the register)."""
    out: list[Observation] = []
    for doc in crawl.docs():
        for org in jsonld_of_type(doc, "Organization", "Corporation", "LocalBusiness"):
            emp = org.get("numberOfEmployees")
            if isinstance(emp, dict):
                emp = emp.get("value") or emp.get("maxValue")
            if isinstance(emp, (int, float, str)) and str(emp).strip().isdigit():
                out.append(Observation(field="reported_employees", value=int(str(emp).strip()), claim_span=f'JSON-LD Organization numberOfEmployees = {emp}',
                                       extraction_method="json_ld", label="Employees (company-reported)", numeric=True, unit="people", as_of=date_only(doc.retrieved_at),
                                       **_page_base(crawl, doc)))
            logo = org.get("logo")
            if isinstance(logo, dict):
                logo = logo.get("url")
            if isinstance(logo, str) and logo.startswith("http"):
                out.append(Observation(field="logo_url", value=logo, claim_span=f"JSON-LD Organization logo = {truncate(logo, 200)}", extraction_method="json_ld",
                                       label="Logo", **_page_base(crawl, doc)))
            if out:
                return out
    return out


def description_observation(crawl: SiteCrawl) -> Observation | None:
    """Deterministic business description: the first substantive paragraph on the About page, else the meta description."""
    if not crawl.verified:
        return None
    for doc in crawl.docs("about") + crawl.docs("products"):
        for para in doc.paragraphs[:12]:
            if 80 <= len(para) <= 700 and not re.search(r"(cookie|personvern|privacy|javascript|©)", para, re.I):
                return Observation(field="business_description", value=para, claim_span=para, extraction_method="page_paragraph",
                                   label="What the company does (company-stated)", document_title=doc.title or None, excerpt_language=_lang(doc),
                                   **_page_base(crawl, doc))
    home = crawl.homepage
    if home is not None:
        desc = home.description or home.og.get("description")
        if desc and len(desc) >= 60:
            return Observation(field="business_description", value=desc, claim_span=desc, extraction_method="html_meta",
                               label="What the company does (company-stated)", document_title=home.title or None, excerpt_language=_lang(home),
                               **_page_base(crawl, home))
    return None


def news_observations(crawl: SiteCrawl, *, limit: int = 8) -> list[Observation]:
    """Dated news items published on the verified site (newsroom / press pages)."""
    if not crawl.verified:
        return []
    items: dict[str, Observation] = {}
    for doc in crawl.docs("news") + crawl.docs("investors"):
        for art in jsonld_of_type(doc, "NewsArticle", "Article", "BlogPosting", "PressRelease"):
            title = clean_ws(str(art.get("headline") or art.get("name") or ""))
            date = date_only(str(art.get("datePublished") or art.get("dateCreated") or ""))
            if len(title) >= NEWS_TITLE_MIN and date:
                key = f"{date}|{title.casefold()}"
                items.setdefault(key, Observation(field="news_item", value=title, key_suffix=key, as_of=date, effective_from=date,
                                                  claim_span=f'{art.get("@type")} "{truncate(title, 200)}" datePublished {date}', extraction_method="json_ld",
                                                  label="Company news", attributes={"url": art.get("url") or doc.final_url, "date": date},
                                                  document_title=doc.title or None, **_page_base(crawl, doc)))
        for t in doc.times:
            dt = parse_iso(t.datetime) or (parse_iso(t.datetime[:10] + "T00:00:00Z") if re.match(r"\d{4}-\d{2}-\d{2}", t.datetime) else None)
            if not dt:
                continue
            date = dt.date().isoformat()
            title = clean_ws(t.context.replace(t.text, "", 1))[:180]
            if len(title) < NEWS_TITLE_MIN:
                continue
            key = f"{date}|{title.casefold()[:80]}"
            if key in items:
                continue
            items[key] = Observation(field="news_item", value=truncate(title, 180), key_suffix=key, as_of=date, effective_from=date,
                                     claim_span=truncate(t.context, 300), extraction_method="time_element", label="Company news",
                                     attributes={"url": doc.final_url, "date": date}, document_title=doc.title or None, **_page_base(crawl, doc))
    ordered = sorted(items.values(), key=lambda o: o.as_of or "", reverse=True)
    return ordered[:limit]


def job_observations(crawl: SiteCrawl, jobs: list[JobItem], status_note: str, checked: bool) -> list[Observation]:
    """Job postings (current and stale) and the current-openings count.

    ``open_positions_count`` is only published when company-owned careers sources
    were actually checked — 0 from a checked careers page is a real value, a
    site without any careers page yields no count at all.
    """
    if not crawl.verified:
        return []
    obs: list[Observation] = []
    for job in jobs:
        base = {
            "module": "jobs", "source_id": "jobs", "source_name": f"Company careers ({job.source_host})",
            "source_class": "company_owned" if job.method in ("json_ld", "careers_page_link") and job.source_host.endswith(crawl.domain) else "company_linked_job_board",
            "source_url": job.url if job.method == "json_ld" and job.url.startswith("http") else job.source_url, "retrieved_at": job.retrieved_at,
            "content_sha256": job.content_sha256, "tier": "B", "identity_score": crawl.audit.score if crawl.audit else 0.0,
        }
        obs.append(Observation(field="job_posting", value=job.title, key_suffix=job.id, claim_span=job.evidence_span or job.title, extraction_method=job.method,
                               label="Job posting", current=job.state == "current", as_of=job.posted_at, effective_from=job.posted_at, effective_to=job.valid_through,
                               attributes={"location": job.location, "department": job.department, "employment_type": job.employment_type, "state": job.state,
                                           "url": job.url, "posted_at": job.posted_at, "valid_through": job.valid_through}, **base))
    current = [j for j in jobs if j.state == "current"]
    if checked:
        src = next((o for o in obs if o.current), None)
        careers = (crawl.docs("careers") or [crawl.homepage])[0] if (crawl.docs("careers") or crawl.homepage) else None
        if src is not None:
            obs.append(Observation(field="open_positions_count", value=len(current), claim_span=f"{len(current)} current posting(s): " + "; ".join(j.title for j in current[:5]),
                                   extraction_method="count_of_postings", label="Open positions", numeric=True, unit="roles", as_of=date_only(src.retrieved_at),
                                   **{k: getattr(src, k) for k in ("module", "source_id", "source_name", "source_class", "source_url", "retrieved_at", "content_sha256", "tier", "identity_score")}))
        elif careers is not None and crawl.docs("careers") and not jobs and (no_openings := _explicit_no_openings(crawl.docs("careers"))):
            # Only an explicit statement on the careers page proves zero; a page that loads jobs by script proves nothing.
            obs.append(Observation(field="open_positions_count", value=0, claim_span=truncate(no_openings, 280), extraction_method="checked_careers_page",
                                   label="Open positions", numeric=True, unit="roles", as_of=date_only(careers.retrieved_at), **{**_page_base(crawl, careers), "module": "jobs",
                                                                                                                                 "source_id": "jobs"}))
    return obs


NO_OPENINGS = re.compile(
    r"(ingen ledige stillinger|ingen ledige jobber|har ingen ledige|ingen utlyste stillinger|no (current )?(open|vacant) (positions|roles|jobs)|no vacancies|no current openings"
    r"|there are no open positions|we have no open positions)", re.I)


def _explicit_no_openings(docs: list[PageDoc]) -> str | None:
    for doc in docs:
        m = NO_OPENINGS.search(doc.text)
        if m:
            return find_span(doc.text, m.group(0), radius=60)
    return None


def quote_in_pages(quote: str, docs: list[PageDoc]) -> PageDoc | None:
    """Return the page that contains ``quote`` verbatim (whitespace/case-insensitive)."""
    from .html import text_contains

    for doc in docs:
        if text_contains(doc.text, quote) or text_contains(" ".join(doc.paragraphs), quote) or text_contains(doc.description, quote):
            return doc
    return None


def excerpt_for(doc: PageDoc, needle: str) -> str:
    return find_span(doc.text, needle, radius=80)
