"""Deterministic exact-entity matching for web pages.

The score is a sum of independent identity signals; a conflicting organisation
number vetoes publication. Thresholds are deliberately strict — a smaller
correct profile beats a richer wrong one.

    org number shown on the site ............. 0.90  (very strong)
    domain holder = org number (Norid) ....... 0.60
    site listed as website in the register ... 0.45
    exact legal name on the site ............. 0.35
    registered e-mail address on the site .... 0.35
    registered street address on the site .... 0.30
    registered phone number on the site ...... 0.30
    e-mail domain of the register = site ..... 0.30
    distinctive brand tokens on the site ..... 0.20
    former legal name on the site ............ 0.15
    brand token in the domain ................ 0.10  (weak)
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
    distinctive_tokens,
    email_domain,
    find_org_numbers,
    name_in_text,
    normalize_phone,
    normalize_street,
    phones_in_text,
)

VERIFIED_THRESHOLD = 0.75  # any site
REGISTRY_LINKED_THRESHOLD = 0.60  # site the register itself lists for the company
WEIGHTS = {
    "org_number_on_site": 0.90,
    "norid_holder_match": 0.60,
    "registry_listed_website": 0.45,
    "legal_name_on_site": 0.35,
    "registered_email_on_site": 0.35,
    "registered_address_on_site": 0.30,
    "registered_phone_on_site": 0.30,
    "registered_email_domain": 0.30,
    "brand_tokens_on_site": 0.20,
    "former_name_on_site": 0.15,
    "brand_token_in_domain": 0.10,
}

Decision = Literal["verified", "ambiguous", "rejected"]


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


def audit_site(
    identity: CanonicalIdentity,
    pages: list[PageDoc],
    domain: str,
    *,
    registry_linked: bool = False,
    norid_holder_org: str | None = None,
    parked: bool = False,
) -> IdentityAudit:
    audit = IdentityAudit(domain=domain, score=0.0, decision="ambiguous", pages_checked=[p.final_url for p in pages], parked=parked)
    if not pages:
        audit.decision = "rejected"
        audit.conflicts.append("no pages retrieved")
        return audit
    target = identity.org_number
    combined = "\n".join(" ".join([p.title, p.og.get("site_name", ""), p.description, p.text, p.footer_text, " ".join(_jsonld_ids(p))]) for p in pages)

    def add(signal: str, excerpt: str | None = None) -> None:
        if signal not in audit.signals:
            audit.signals.append(signal)
            audit.score += WEIGHTS[signal]
            if excerpt:
                audit.evidence[signal] = excerpt[:300]

    numbers = find_org_numbers(combined)
    if any(num == target for num, _ in numbers):
        digits = f"{target[:3]} {target[3:6]} {target[6:]}"
        span = _excerpt(combined, target) if target in combined else _excerpt(combined, digits)
        add("org_number_on_site", span)
    others = [num for num, in_context in numbers if num != target and in_context]
    if others and "org_number_on_site" not in audit.signals:
        audit.conflicts.append(f"site shows a different organisation number: {', '.join(sorted(set(others))[:3])}")

    if norid_holder_org:
        if norid_holder_org == target:
            add("norid_holder_match", f"Domain holder organisation number {target}")
        else:
            audit.conflicts.append(f"domain holder is organisation {norid_holder_org}")
    if registry_linked:
        add("registry_listed_website", f"Enhetsregisteret lists {identity.website_raw or identity.website} as the company's website")
    if identity.legal_name and name_in_text(identity.legal_name, combined):
        add("legal_name_on_site", _excerpt(combined, identity.legal_name))
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
        add("registered_email_domain", f"Registered e-mail {identity.email}")
    tokens = distinctive_tokens(identity.legal_name)
    if tokens:
        surface = fold(" ".join(p.title + " " + p.og.get("site_name", "") + " " + p.text[:4000] for p in pages))
        if all(re.search(rf"\b{re.escape(t)}\b", surface) for t in tokens):
            add("brand_tokens_on_site", " ".join(tokens))
        ascii_domain = ascii_fold(domain.split(".")[0])
        if any(len(t) >= 4 and ascii_fold(t) in ascii_domain for t in tokens):
            add("brand_token_in_domain", domain)
    for former in identity.former_names or []:
        if former.get("name") and name_in_text(former["name"], combined):
            add("former_name_on_site", _excerpt(combined, former["name"]))
            break

    audit.score = round(audit.score, 3)
    threshold = REGISTRY_LINKED_THRESHOLD if registry_linked else VERIFIED_THRESHOLD
    if parked:
        audit.decision = "rejected"
        audit.conflicts.append("domain appears parked or under construction")
    elif audit.conflicts and "org_number_on_site" not in audit.signals:
        audit.decision = "rejected" if not registry_linked else "ambiguous"
    elif audit.score >= threshold:
        audit.decision = "verified"
    else:
        audit.decision = "ambiguous"
    return audit
