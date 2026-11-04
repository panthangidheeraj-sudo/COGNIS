"""Deterministic exact-entity matching for web pages.

The score is a sum of independent identity signals; a conflicting organisation
number vetoes publication. Thresholds are deliberately strict — a smaller
correct profile beats a richer wrong one.

    org number shown on the site ............. 0.90  (very strong)
    domain holder = org number (Norid) ....... 0.60  (the domain registry names this exact entity)
    exact legal name on the site ............. 0.35
    registered e-mail address on the site .... 0.35
    registered street address on the site .... 0.30
    registered phone number on the site ...... 0.30
    distinctive brand tokens on the site ..... 0.20
    former legal name on the site ............ 0.15

Version 2: signals that come from the register itself or from the domain *name* (the site is listed as the website in Enhetsregisteret, the register's
e-mail address uses this domain, a brand word appears in the domain) say where a candidate came from. They are recorded as ``context_signals`` and never
count towards ``score``: a site is verified only by evidence the *site or the domain registry* provides about the exact legal entity. A site that presents
itself as the parent group, or that lists several legal entities with their organisation numbers, is a group website and is never published as the
individual company's own site (unless the domain registry names the company as the holder).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from ..core.util import fold
from ..extraction.html import PageDoc
from .model import CanonicalIdentity
from .normalization import (
    WEBMAIL_DOMAINS,
    ascii_fold,
    continues_into_longer_name,
    distinctive_tokens,
    email_domain,
    find_org_numbers,
    name_in_text,
    normalize_phone,
    normalize_street,
    phones_in_text,
)

VERIFIED_THRESHOLD = 0.75  # any discovered site
REGISTRY_LINKED_THRESHOLD = 0.65  # site the register or the company's contact details point at (independent evidence only)
WEIGHTS = {
    "org_number_on_site": 0.90,
    "norid_holder_match": 0.60,
    "legal_name_on_site": 0.35,
    "registered_email_on_site": 0.35,
    "registered_address_on_site": 0.30,
    "registered_phone_on_site": 0.30,
    "brand_tokens_on_site": 0.20,
    "former_name_on_site": 0.15,
}

# Signals that describe where the candidate came from, not what the site shows. Recorded, never scored.
CONTEXT_WEIGHTS = {"registry_listed_website": 0.45, "registered_email_domain": 0.30, "brand_token_in_domain": 0.10}
INDEPENDENT_THRESHOLD = 0.65  # a candidate the register / contact details pointed at: needs name + one more on-site identifier (address, phone or e-mail)
DISCOVERED_THRESHOLD = 0.75  # a candidate found by search or by guessing: needs more

Decision = Literal["verified", "ambiguous", "rejected"]
Scope = Literal["company", "group", "unknown"]


@dataclass
class IdentityAudit:
    domain: str
    score: float
    decision: Decision
    signals: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)  # signal → exact supporting excerpt
    pages_checked: list[str] = field(default_factory=list)
    parked: bool = False
    context_signals: list[str] = field(default_factory=list)  # where the candidate came from (register listing, e-mail domain, brand word in domain): never scored
    scope: Scope = "unknown"  # company | group | unknown: does the site present THIS legal entity, or its parent / a group of entities?
    reasons: list[str] = field(default_factory=list)  # why the candidate was verified, left ambiguous or rejected, in plain words

    def to_dict(self) -> dict:
        return asdict(self)


def _excerpt(text: str, needle: str, radius: int = 70) -> str:
    idx = fold(text).find(fold(needle))
    if idx < 0:
        return needle
    return text[max(0, idx - radius): idx + len(needle) + radius].strip()


def _jsonld_ids(doc: PageDoc) -> list[str]:
    values: list[str] = []
    for item in doc.jsonld:
        for key in ("vatID", "taxID", "identifier", "leiCode", "duns", "organizationNumber"):
            v = item.get(key)
            if isinstance(v, dict):
                v = v.get("value")
            if v:
                values.append(str(v))
    return values


def _surface(page: PageDoc) -> str:
    """What a page says about WHO it is: title, site name, first headings and the footer (not the whole body)."""
    return " ".join([page.title, page.og.get("site_name", ""), " ".join(page.headings[:3]), page.footer_text[:600]])


def related_names_of(observations: list) -> list[dict]:
    """Parent / ultimate-parent entities from the group register, as ``[{"name": ..., "org": ...}]`` (empty when the register lists none)."""
    out: list[dict] = []
    for o in observations:
        if getattr(o, "field", None) in ("parent_company", "ultimate_parent_company"):
            attrs = getattr(o, "attributes", None) or {}
            name = str(o.value)
            if not name.isdigit():
                out.append({"name": name, "org": attrs.get("organisation_number")})
    return out


def audit_site(
    identity: CanonicalIdentity,
    pages: list[PageDoc],
    domain: str,
    *,
    registry_linked: bool = False,
    norid_holder_org: str | None = None,
    parked: bool = False,
    related: list[dict] | None = None,
) -> IdentityAudit:
    """Decide whether ``pages`` (from ``domain``) belong to THIS legal entity.

    ``registry_linked`` says the candidate came from the register or the company's own contact details. That is where it came from, not proof: it lowers
    the bar slightly (0.65 instead of 0.75) but is never scored itself. ``related`` lists the parent entities from the group register, so that a parent
    group's corporate site is not mistaken for the subsidiary's own."""
    audit = IdentityAudit(domain=domain, score=0.0, decision="ambiguous", pages_checked=[p.final_url for p in pages], parked=parked)
    if not pages:
        audit.decision = "rejected"
        audit.conflicts.append("no pages retrieved")
        audit.reasons.append("the candidate could not be fetched, so nothing on it could be checked")
        return audit
    target = identity.org_number
    combined = "\n".join(" ".join([p.title, p.og.get("site_name", ""), p.description, p.text, p.footer_text, " ".join(_jsonld_ids(p))]) for p in pages)

    def add(signal: str, excerpt: str | None = None) -> None:
        if signal not in audit.signals:
            audit.signals.append(signal)
            audit.score += WEIGHTS[signal]
            if excerpt:
                audit.evidence[signal] = excerpt[:300]

    def context(signal: str, excerpt: str) -> None:
        if signal not in audit.context_signals:
            audit.context_signals.append(signal)
            audit.evidence.setdefault(signal, excerpt[:300])

    numbers = find_org_numbers(combined)
    org_on_site = any(num == target for num, _ in numbers)
    if org_on_site:
        digits = f"{target[:3]} {target[3:6]} {target[6:]}"
        span = _excerpt(combined, target) if target in combined else _excerpt(combined, digits)
        add("org_number_on_site", span)
    others = [num for num, in_context in numbers if num != target and in_context]
    if others and not org_on_site:
        audit.conflicts.append(f"site shows a different organisation number: {', '.join(sorted(set(others))[:3])}")
    group_listing = bool(org_on_site and others)
    if group_listing:
        audit.conflicts.append(f"site lists several legal entities with organisation numbers ({', '.join(sorted(set(others))[:3])} besides this company): a group website")

    holder_ok = False
    if norid_holder_org:
        if norid_holder_org == target:
            holder_ok = True
            add("norid_holder_match", f"Domain holder organisation number {target}")
        else:
            audit.conflicts.append(f"domain holder is organisation {norid_holder_org}")
    if registry_linked:
        context("registry_listed_website", f"Enhetsregisteret lists {identity.website_raw or identity.website} as the company's website (this says where the candidate came from, not that it is the company's)")

    legal = identity.legal_name or ""
    name_here = name_in_text(legal, combined) and not continues_into_longer_name(combined, legal)
    if name_here:
        add("legal_name_on_site", _excerpt(combined, legal))
    if identity.email and identity.email.lower() in combined.lower():
        add("registered_email_on_site", _excerpt(combined, identity.email))
    street_lines = (identity.business_address or {}).get("adresse") or (identity.postal_address or {}).get("adresse") or []
    norm_text = normalize_street(combined)
    for line in street_lines:
        street = normalize_street(line)
        if len(street) >= 6 and re.search(r"\d", street) and f" {street} " in f" {norm_text} ":
            add("registered_address_on_site", _excerpt(combined, line))
            break
    if identity.phone:
        phone = normalize_phone(identity.phone)
        page_phones = phones_in_text(combined) | {normalize_phone(p) for doc in pages for p in doc.phones}
        if phone and phone in page_phones:
            add("registered_phone_on_site", f"Telephone {identity.phone}")
    mail_domain = email_domain(identity.email)
    if mail_domain and mail_domain not in WEBMAIL_DOMAINS and (mail_domain == domain or mail_domain.endswith("." + domain)):
        context("registered_email_domain", f"Registered e-mail {identity.email} uses this domain (the register's own data: it does not show what the site says)")
    tokens = distinctive_tokens(identity.legal_name)
    if tokens:
        surface = fold(" ".join(p.title + " " + p.og.get("site_name", "") + " " + p.text[:4000] for p in pages))
        if all(re.search(rf"\b{re.escape(t)}\b", surface) for t in tokens):
            add("brand_tokens_on_site", " ".join(tokens))
        ascii_domain = ascii_fold(domain.split(".")[0])
        if any(len(t) >= 4 and ascii_fold(t) in ascii_domain for t in tokens):
            context("brand_token_in_domain", domain)
    for former in identity.former_names or []:
        if former.get("name") and name_in_text(former["name"], combined):
            add("former_name_on_site", _excerpt(combined, former["name"]))
            break

    # Does the site present THIS entity, or its parent group? The parent's name in the site's own identity (title, site name, headings, footer) without this
    # company's name there means the group's corporate site.
    home_surface = " ".join(_surface(p) for p in pages[:2])
    parent_on_identity = next((r for r in related or [] if r.get("name") and name_in_text(r["name"], home_surface) and not continues_into_longer_name(home_surface, r["name"])), None)
    own_on_identity = name_in_text(legal, home_surface) and not continues_into_longer_name(home_surface, legal)
    if parent_on_identity and not own_on_identity and not holder_ok:
        audit.scope = "group"
        audit.conflicts.append(f"site presents the parent group ({parent_on_identity['name']}), not this company")
    elif group_listing:
        audit.scope = "group"
    elif org_on_site or holder_ok or audit.score > 0:
        audit.scope = "company"

    audit.score = round(audit.score, 3)
    threshold = REGISTRY_LINKED_THRESHOLD if registry_linked else VERIFIED_THRESHOLD
    strong = holder_ok or org_on_site
    if parked:
        audit.decision = "rejected"
        audit.conflicts.append("domain appears parked or under construction")
        audit.reasons.append("the domain looks parked or under construction")
    elif audit.scope == "group" and not holder_ok:
        audit.decision = "ambiguous"
        audit.reasons.append("the site is a parent-group or multi-entity website, so it is not published as this individual company's own website")
    elif audit.conflicts and not strong:
        audit.decision = "rejected" if not registry_linked else "ambiguous"
        audit.reasons.append("the site contradicts this company's identity: " + "; ".join(audit.conflicts[:2]))
    elif strong or audit.score >= threshold:
        audit.decision = "verified"
        audit.reasons.append("verified by " + ", ".join(s.replace("_", " ") for s in audit.signals))
    else:
        audit.decision = "ambiguous"
        have = ", ".join(s.replace("_", " ") for s in audit.signals) or "none"
        extra = f" (it is only {'listed in the register' if 'registry_listed_website' in audit.context_signals else 'a candidate'}; that alone proves nothing)" if audit.score < threshold else ""
        audit.reasons.append(f"not enough evidence on the site itself that it belongs to this exact entity: on-site/registry evidence {have}, score {audit.score:.2f} < {threshold:.2f}{extra}")
    return audit
