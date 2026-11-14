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

Version 3 (re-scoring fix): a name, address, telephone number or e-mail address that appears *somewhere on a page* does not prove the page belongs to the entity — a
property manager, a housing association, a board-portal platform or a directory lists many cooperatives with their (often shared, c/o) contact details. Therefore:

* name / address / telephone / e-mail count towards verification only when the site *presents itself as this entity* (its own name in the title, site name, main
  headings, footer or structured data) — never from a customer list, tenant list or portal page about someone else;
* an organisation number counts as ownership only in the site's own identity zone (footer, structured data, or a page that presents the entity), never from a list;
* a site whose identity is a manager / housing association / platform / directory (and not this entity) is never published, whatever it lists;
* shared-management entity types (borettslag, sameie, eierseksjonssameie, ...) need exact organisation-number evidence or a Norid domain-holder match to the exact
  organisation: contact details alone can never verify them.
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
    normalize_name,
    normalize_phone,
    normalize_street,
    phones_in_text,
    spell_as,
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
Scope = Literal["company", "group", "manager", "directory", "unknown"]

# Entity types that are typically administered by a third party (a property manager, housing association or board-portal platform). Their registered address,
# telephone number and e-mail are very often the manager's, shared by many entities — contact details can never establish who owns a website for them.
SHARED_MANAGEMENT_FORMS = {"BRL", "ESEK", "SAM"}
SHARED_MANAGEMENT_NAME = re.compile(r"\b(borettslag|boligsameie|eierseksjonssameie|sameie|boligselskap|velforening|garasjelag|parkeringslag)\b", re.I)
# Words that, in the title / site name / headings / footer of a site that does NOT name this entity, say whose site it is: a manager, a housing association or a portal.
MANAGER_MARKERS = re.compile(r"\b(boligbyggelag|boligbygg|forretningsf[øo]r\w*|eiendomsforvalt\w*|boligforvalt\w*|forvaltning|styrerom\w*|styreportal\w*|beboerportal\w*|"
                             r"bor?ettslagsportal\w*|sameieportal\w*|sameieadministr\w*|borettslag\s+og\s+sameier|boligselskaper|obos|nbbl|usbl|bbl)\b", re.I)
# A list of housing entities ("Våre borettslag: A BORETTSLAG, B BORETTSLAG, ...") is a customer / member list, whatever page it sits on.
_HOUSING_ENTITY = re.compile(r"\b[A-ZÆØÅ][\wæøåÆØÅ.\-]*(?:\s+[A-ZÆØÅ0-9][\wæøåÆØÅ.\-]*){0,5}\s+(?i:borettslag|eierseksjonssameie|boligsameie|sameie|boligselskap)\b")
LISTING_MIN_ENTITIES = 3
# Directories, registries and aggregators describe many companies: a page on them is never the company's own website.
DIRECTORY_DOMAINS = {
    "proff.no", "purehelp.no", "gulesider.no", "1881.no", "180.no", "regnskapstall.no", "firmaonline.no", "kompass.com", "enirogate.no", "infobel.com", "dnb.com",
    "bisnode.no", "forvalt.no", "allabolag.se", "opencorporates.com", "northdata.com", "northdata.de", "eniro.no", "krak.no", "firmasok.no", "regnskapsbanken.no",
    "ravninfo.com", "brreg.no", "foretaksregisteret.no", "bizzdo.no", "linkedin.com", "facebook.com", "finn.no",
}


def is_shared_management_entity(identity: CanonicalIdentity) -> bool:
    """Borettslag, sameie, eierseksjonssameie and similar: entities whose contact details are usually a manager's."""
    return (identity.legal_form or "").upper() in SHARED_MANAGEMENT_FORMS or bool(SHARED_MANAGEMENT_NAME.search(identity.legal_name or ""))


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
    risk: str = "standard"  # standard | shared_management_entity (borettslag, sameie, ...: contact details never verify)
    shared_signals: list[str] = field(default_factory=list)  # contact details / names found on the site that were NOT counted, because the site does not present this entity
    presents_entity: bool = False  # does the site itself (title, headings, footer, structured data) name this legal entity?
    other_party: bool = False  # the site demonstrably belongs to someone else (a manager, portal, directory, or the domain holder / organisation number on it is another entity)

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


def _identity_zone(page: PageDoc) -> str:
    """The parts of a page that say who the site is: title, site name, first headings, footer and the organisation identifiers in structured data."""
    return " ".join([page.title, page.og.get("site_name", ""), " ".join(page.headings[:3]), page.footer_text[:1200], " ".join(_jsonld_ids(page))])


def _jsonld_names(page: PageDoc) -> list[str]:
    names: list[str] = []
    for item in page.jsonld:
        for key in ("legalName", "name"):
            v = item.get(key)
            if isinstance(v, str) and v.strip():
                names.append(v)
    return names


def _page_presents_entity(identity: CanonicalIdentity, page: PageDoc) -> bool:
    """Does THIS page present itself as the entity: its legal name in the title / site name / headings / footer, all distinctive name words in the title, site
    name or main headings, or its legal name in structured data (an Organization entry)? A name inside a list or paragraph does not count."""
    legal = spell_as(identity.legal_name)  # "AUTOBJØRN A/S" is the legal form AS, however a page spells it
    zone = _surface(page)
    if name_in_text(legal, zone) and not continues_into_longer_name(zone, legal):
        return True
    heading = fold(" ".join([page.title, page.og.get("site_name", ""), " ".join(page.headings[:2])]))
    tokens = distinctive_tokens(legal)
    if tokens and all(re.search(rf"\b{re.escape(t)}\b", heading) for t in tokens) and not continues_into_longer_name(heading, legal):
        return True
    return any(name_in_text(legal, n) and not continues_into_longer_name(n, legal) for n in _jsonld_names(page))


def _listed_housing_entities(pages: list[PageDoc], legal_name: str | None) -> list[str]:
    """Distinct housing entities (…borettslag, …sameie) named on the pages, other than this one: a member / customer list."""
    own = " ".join(normalize_name(legal_name).split())
    found: dict[str, str] = {}
    for page in pages:
        for m in _HOUSING_ENTITY.finditer(page.text or ""):
            key = " ".join(normalize_name(m.group(0)).split())
            if key and key != own:
                found.setdefault(key, m.group(0))
    return sorted(found.values())


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
    shared_risk = is_shared_management_entity(identity)
    audit = IdentityAudit(domain=domain, score=0.0, decision="ambiguous", pages_checked=[p.final_url for p in pages], parked=parked,
                          risk="shared_management_entity" if shared_risk else "standard")
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

    # ---- who does the site say it is? ------------------------------------------------------------------------------------------------------------------
    presenting = [p for p in pages if _page_presents_entity(identity, p)]
    presents = bool(presenting)
    audit.presents_entity = presents
    home = pages[0]
    home_zone = _surface(home)
    marker = MANAGER_MARKERS.search(home_zone)
    listed = _listed_housing_entities(pages, identity.legal_name)
    directory = domain in DIRECTORY_DOMAINS

    def shared(signal: str, excerpt: str) -> None:
        """Found on the site, but the site does not present this entity: it may be a manager's / portal's / directory's data about it. Recorded, never scored."""
        if signal not in audit.shared_signals:
            audit.shared_signals.append(signal)
            audit.evidence.setdefault(f"{signal}_not_counted", excerpt[:300])

    numbers = find_org_numbers(combined)
    org_on_site = any(num == target for num, _ in numbers)
    zone_numbers = {num for num, _ in find_org_numbers(" ".join(_identity_zone(p) for p in pages))}
    org_in_zone = target in zone_numbers
    others = [num for num, in_context in numbers if num != target and in_context]
    if others and not org_on_site:
        audit.conflicts.append(f"site shows a different organisation number: {', '.join(sorted(set(others))[:3])}")
    group_listing = bool(org_on_site and others)
    if group_listing:
        audit.conflicts.append(f"site lists several legal entities with organisation numbers ({', '.join(sorted(set(others))[:3])} besides this company): a group website")
    # The number only counts as ownership where the site speaks about itself (footer, structured data, a page that presents the entity) — not in a list or portal.
    org_ok = org_on_site and not group_listing and (org_in_zone or presents)
    if org_ok:
        digits = f"{target[:3]} {target[3:6]} {target[6:]}"
        add("org_number_on_site", _excerpt(combined, target) if target in combined else _excerpt(combined, digits))
    elif org_on_site:
        shared("org_number_on_site", _excerpt(combined, target) if target in combined else _excerpt(combined, f"{target[:3]} {target[3:6]} {target[6:]}"))

    holder_ok = False
    holder_conflict = False
    if norid_holder_org:
        if norid_holder_org == target:
            holder_ok = True
            add("norid_holder_match", f"Domain holder organisation number {target}")
        else:
            holder_conflict = True
            audit.conflicts.append(f"domain holder is organisation {norid_holder_org}")
    if registry_linked:
        context("registry_listed_website", f"Enhetsregisteret lists {identity.website_raw or identity.website} as the company's website (this says where the candidate came from, not that it is the company's)")

    legal = identity.legal_name or ""
    name_here = name_in_text(legal, combined) and not continues_into_longer_name(combined, legal)
    if not name_here:  # an Organization entry in structured data that names the entity is the page identifying itself, though the name is not in the visible text
        spelled = spell_as(legal)
        name_here = any(name_in_text(spelled, n) and not continues_into_longer_name(n, spelled) for p in pages for n in _jsonld_names(p))
    if name_here:
        add("legal_name_on_site", _excerpt(combined, legal))
    # Contact details count only when the site presents this entity (or the domain registry names it as holder): a manager, portal or directory shows the registered
    # address / telephone / e-mail of the entities it administers, and several entities share one manager's details.
    contact_counts = presents or holder_ok
    if identity.email and identity.email.lower() in combined.lower():
        (add if contact_counts else shared)("registered_email_on_site", _excerpt(combined, identity.email))
    street_lines = (identity.business_address or {}).get("adresse") or (identity.postal_address or {}).get("adresse") or []
    norm_text = normalize_street(combined)
    for line in street_lines:
        street = normalize_street(line)
        if len(street) >= 6 and re.search(r"\d", street) and f" {street} " in f" {norm_text} ":
            (add if contact_counts else shared)("registered_address_on_site", _excerpt(combined, line))
            break
    if identity.phone:
        phone = normalize_phone(identity.phone)
        page_phones = phones_in_text(combined) | {normalize_phone(p) for doc in pages for p in doc.phones}
        if phone and phone in page_phones:
            (add if contact_counts else shared)("registered_phone_on_site", f"Telephone {identity.phone}")
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

    # ---- is the site a group, a manager / housing association / portal, or a directory? ------------------------------------------------------------------
    home_surface = " ".join(_surface(p) for p in pages[:2])
    parent_on_identity = next((r for r in related or [] if r.get("name") and name_in_text(r["name"], home_surface) and not continues_into_longer_name(home_surface, r["name"])), None)
    own_on_identity = name_in_text(legal, home_surface) and not continues_into_longer_name(home_surface, legal)
    third_party_reason: str | None = None
    if directory:
        audit.scope = "directory"
        third_party_reason = f"{domain} is a directory or register that describes many companies, not this company's own website"
    elif marker is not None and not name_in_text(legal, home_zone) and not holder_ok:
        audit.scope = "manager"
        third_party_reason = (f"the site presents itself as '{marker.group(0)}' (a property manager, housing association or portal), not as this entity: "
                              "what it shows about this entity is a listing, not ownership")
    elif len(listed) >= LISTING_MIN_ENTITIES and not own_on_identity and not holder_ok:
        audit.scope = "manager"
        third_party_reason = f"the site lists {len(listed)} housing entities (for example {listed[0]}): a member / customer list, which does not prove any one of them owns the site"
    elif parent_on_identity and not own_on_identity and not holder_ok:
        audit.scope = "group"
        audit.conflicts.append(f"site presents the parent group ({parent_on_identity['name']}), not this company")
    elif group_listing:
        audit.scope = "group"
    elif org_ok or holder_ok or audit.score > 0:
        audit.scope = "company"
    if third_party_reason:
        audit.conflicts.append(third_party_reason)

    audit.score = round(audit.score, 3)
    audit.other_party = bool(not holder_ok and (audit.scope in ("manager", "directory") or holder_conflict or (others and not org_on_site)))
    threshold = REGISTRY_LINKED_THRESHOLD if registry_linked else VERIFIED_THRESHOLD
    strong = holder_ok or org_ok
    independent_contact = bool({"registered_address_on_site", "registered_phone_on_site", "registered_email_on_site"} & set(audit.signals))
    if parked:
        audit.decision = "rejected"
        audit.conflicts.append("domain appears parked or under construction")
        audit.reasons.append("the domain looks parked or under construction")
    elif audit.scope in ("directory", "manager") and not holder_ok:
        audit.decision = "rejected" if (audit.scope == "directory" or holder_conflict) else "ambiguous"
        audit.reasons.append("not published as this entity's website: " + (third_party_reason or "the site belongs to a third party"))
    elif audit.scope == "group" and not holder_ok:
        audit.decision = "ambiguous"
        audit.reasons.append("the site is a parent-group or multi-entity website, so it is not published as this individual company's own website")
    elif audit.conflicts and not strong:
        audit.decision = "rejected" if (not registry_linked or holder_conflict) else "ambiguous"
        audit.reasons.append("the site contradicts this company's identity: " + "; ".join(audit.conflicts[:2]))
    elif strong:
        audit.decision = "verified"
        audit.reasons.append("verified by " + ", ".join(s.replace("_", " ") for s in audit.signals))
    elif shared_risk:
        audit.decision = "ambiguous"
        audit.reasons.append("housing cooperatives, owner associations and similar entities are usually run by a manager whose address, telephone and e-mail they share: "
                             "without this entity's organisation number in the site's own identity or a Norid domain-holder match, ownership cannot be established"
                             + (f" (found but not counted: {', '.join(s.replace('_', ' ') for s in audit.shared_signals)})" if audit.shared_signals else ""))
    elif presents and independent_contact and audit.score >= threshold:
        audit.decision = "verified"
        audit.reasons.append("verified by " + ", ".join(s.replace("_", " ") for s in audit.signals))
    else:
        audit.decision = "ambiguous"
        have = ", ".join(s.replace("_", " ") for s in audit.signals) or "none"
        extra = f" (it is only {'listed in the register' if 'registry_listed_website' in audit.context_signals else 'a candidate'}; that alone proves nothing)" if audit.score < threshold else ""
        why_not = ""
        if not presents:
            why_not = "; the site does not present this entity in its title, headings, footer or structured data, so a name or contact detail on it proves nothing"
        elif not independent_contact:
            why_not = "; no registered address, telephone or e-mail on the site corroborates the name"
        shared_note = f" (found but not counted: {', '.join(s.replace('_', ' ') for s in audit.shared_signals)})" if audit.shared_signals else ""
        audit.reasons.append(f"not enough evidence on the site itself that it belongs to this exact entity: on-site/registry evidence {have}, score {audit.score:.2f} vs {threshold:.2f}{extra}{why_not}{shared_note}")
    return audit
