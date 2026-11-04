"""Social-profile verification: a link in a website footer is a *candidate*, never evidence by itself.

A company site often links the web agency that built it, the CMS theme vendor, the parent group or a sister company in another country. Publishing every
footer link as "the company's profile" attributes someone else's page to the company. A candidate is therefore accepted only when something ties it to this
exact legal entity, and every rejected or unverified candidate is kept (with its reason) for diagnostics.

Decisions
    accepted    the handle carries this company's name (or the verified domain's brand label) and no rejection rule fired
    rejected    a concrete reason: platform/share/own-network page, web agency or theme vendor, parent group, other-country group page
                (profile pages are not fetched: the networks forbid automated reads, so only the handle is judged)
    unverified  nothing ties the link to the company and nothing contradicts it: not published
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from .model import CanonicalIdentity
from .normalization import ascii_fold, distinctive_tokens, name_tokens, spell_as

Decision = Literal["accepted", "rejected", "unverified"]

PLATFORM_HANDLES = {"facebook", "fb", "twitter", "x", "instagram", "linkedin", "youtube", "meta", "pages", "profile.php", "groups", "company", "business", "policies",
                    "help", "about", "legal", "privacy", "tr", "ads", "sharer", "share", "intent", "plugins", "dialog"}
AGENCY_HINTS = ("wordpress", "woocommerce", "elementor", "envato", "themeforest", "themeisle", "wixcom", "squarespace", "shopify", "webflow", "jimdo", "godaddy",
                "mailchimp", "hubspot", "webdesign", "webbyra", "webagency", "webagentur", "digitalbyra", "digitalagency", "reklamebyra", "markedsbyra", "nettside",
                "netthandel", "poweredby", "designedby", "developedby", "madeby", "creativeagency", "webutvikling", "webhotel")
FOREIGN_MARKERS = ("sverige", "sweden", "svenska", "danmark", "denmark", "suomi", "finland", "deutschland", "germany", "nederland", "usa", "uk")


@dataclass
class SocialVerdict:
    network: str
    url: str
    handle: str
    page: str
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    basis: str | None = None  # name_in_handle | domain_brand_in_handle | None
    evidence: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def profile(self) -> dict[str, str]:
        """The accepted-profile record the rest of the pipeline consumes."""
        return {"network": self.network, "handle": self.handle, "url": self.url, "page": self.page, "basis": self.basis or "", "evidence": self.evidence or ""}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_fold(text))


def _slugs(text: str) -> set[str]:
    """Spellings a handle may use for a name: ø→o, ø dropped (LinkedIn/Facebook slugs often lose the letter), ø→oe."""
    low = (text or "").lower()
    out = {_slug(low)}
    for repl in ("", "o", "oe"):
        alt = low.replace("ø", repl).replace("æ", repl if repl != "o" else "a").replace("å", repl if repl != "o" else "a")
        out.add(re.sub(r"[^a-z0-9]", "", alt))
    return {x for x in out if x}


def _name_slugs(identity: CanonicalIdentity) -> tuple[set[str], list[set[str]]]:
    return _slugs(" ".join(name_tokens(spell_as(identity.legal_name)))), [_slugs(t) for t in distinctive_tokens(spell_as(identity.legal_name))]


def _handle_has_name(handle_slug: str, full: set[str], tokens: list[set[str]]) -> bool:
    if not handle_slug:
        return False
    if any(len(f) >= 4 and f in handle_slug for f in full):
        return True
    return bool(tokens) and all(any(len(t) >= 3 and t in handle_slug for t in variants) for variants in tokens)


def assess_social(identity: CanonicalIdentity, domain: str, network: str, handle: str, url: str, page: str, *, related: list[dict] | None = None) -> SocialVerdict:
    """Judge a footer/page link from the handle alone (no network)."""
    v = SocialVerdict(network=network, url=url, handle=handle, page=page, decision="unverified")
    hs = _slug(handle)
    full, tokens = _name_slugs(identity)
    own = _handle_has_name(hs, full, tokens)
    brand = _slug(domain.split(".")[0]) if domain else ""
    brand_match = len(brand) >= 4 and (hs == brand or (brand in hs and not tokens) or (hs.startswith(brand) and len(hs) - len(brand) <= 3))

    if not hs or handle.lower() in PLATFORM_HANDLES or hs in {_slug(p) for p in PLATFORM_HANDLES}:
        v.decision, v.reasons = "rejected", [f"'{handle}' is the social network's own page or a share/utility link, not a company profile"]
        return v
    agency = next((h for h in AGENCY_HINTS if h in hs), None)
    if agency and not own:
        v.decision, v.reasons = "rejected", [f"handle looks like a web agency / theme / platform page ('{agency}'), not the company"]
        return v
    for rel in related or []:
        rname = rel.get("name") or ""
        rfull = _slug(" ".join(name_tokens(rname)))
        rtokens = [_slug(t) for t in distinctive_tokens(rname)]
        if rfull and len(rfull) >= 4 and rfull in hs and not own and rfull not in full:
            v.decision, v.reasons = "rejected", [f"handle belongs to the parent group ({rname}), not this company"]
            return v
        if rtokens and all(len(t) >= 3 and t in hs for t in rtokens) and not own and not brand_match:
            v.decision, v.reasons = "rejected", [f"handle belongs to the parent group ({rname}), not this company"]
            return v
    own_name_slug = "".join(full) + "".join("".join(t) for t in tokens)
    marker = next((m for m in FOREIGN_MARKERS if m in hs and m not in own_name_slug), None)
    if marker:
        v.decision, v.reasons = "rejected", [f"handle names another country's group page ('{marker}'); this is a separate legal entity"]
        return v
    if own:
        v.decision, v.basis = "accepted", "name_in_handle"
        v.reasons = [f"handle '{handle}' carries the company's registered name"]
    elif brand_match:
        v.decision, v.basis = "accepted", "domain_brand_in_handle"
        v.reasons = [f"handle '{handle}' matches the verified website's brand ({domain})"]
    else:
        v.reasons = [f"handle '{handle}' does not carry the company's name or the verified domain; linked from the site but not tied to this entity"]
    return v
