"""Social-profile verification: a link in a website footer is a *candidate*, never evidence by itself.

A company site often links the web agency that built it, the CMS theme vendor, the parent group or a sister company in another country. Publishing every
footer link as "the company's profile" attributes someone else's page to the company. A candidate is therefore accepted only when something ties it to this
exact legal entity, and every rejected or unverified candidate is kept (with its reason) for diagnostics.

Decisions
    accepted    the handle IS this company's name (or the verified domain's brand label), optionally with a plain legal-form / country affix ("autobjornas",
                "equinornorge"), and no rejection rule fired
    rejected    a concrete reason: platform/share/own-network page, web agency or theme vendor, parent group, other-country group page, or a handle that merely
                contains the company's name inside a longer one ("equinorfans")
                (profile pages are not fetched: the networks forbid automated reads, so only the handle is judged)
    unverified  nothing ties the link to the company and nothing contradicts it: not published

What "accepted" means: the profile is *linked from the company's identity-verified website* (``verification == "linked_from_company_site"``) and its handle fits
the company. It is never ``platform_verified``: nothing on the platform itself (the profile's own website link, organisation number or verified badge) was read.
How the company declared it sets the confidence: JSON-LD ``sameAs`` (a deliberate machine-readable statement) > footer link > header link > a link inside page
content; the result is scaled by how well the website's own identity was established, so a handle can never be trusted more than the site it was found on.
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
AFFIX_WORDS = ("norge", "norway", "official", "asa", "as", "no", "hq")  # plain additions to a name that do not make it another organisation (longest first)
DECLARATION_CONFIDENCE = {"jsonld_sameAs": 0.85, "footer": 0.80, "header": 0.76, "page_body": 0.62}
DECLARATION_RANK = {"jsonld_sameAs": 4, "footer": 3, "header": 2, "page_body": 1}
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
    declared_by: str = "page_body"  # jsonld_sameAs | footer | header | page_body: how the company's own page presents the link
    match: str | None = None  # exact | affix: whether the handle is the name itself or the name plus a plain affix
    verification: str | None = None  # linked_from_company_site (accepted) | None
    platform_verified: bool = False  # always False: the profile page itself is never read (platform terms)
    confidence: float | None = None  # ceiling for the published claim

    def to_dict(self) -> dict:
        return asdict(self)

    def profile(self) -> dict[str, str]:
        """The accepted-profile record the rest of the pipeline consumes."""
        return {"network": self.network, "handle": self.handle, "url": self.url, "page": self.page, "basis": self.basis or "", "evidence": self.evidence or "",
                "declared_by": self.declared_by, "match": self.match or "", "verification": self.verification or "", "platform_verified": self.platform_verified,
                "confidence": self.confidence}


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


def _only_affixes(rest: str) -> bool:
    """``rest`` (what is left of a handle after the name is removed) is empty or made only of plain affixes."""
    while rest:
        for word in AFFIX_WORDS:
            if rest.startswith(word):
                rest = rest[len(word):]
                break
        else:
            return False
    return True


def _remove_once(handle: str, part: str) -> str | None:
    """``handle`` without one occurrence of ``part``, kept as the text before + after (so affixes on either side can be judged), or None when absent."""
    i = handle.find(part)
    return None if i < 0 else handle[:i] + "|" + handle[i + len(part):]


def _affix_only(rest: str) -> bool:
    before, _, after = rest.partition("|")
    return (not before or _only_affixes(before)) and (not after or _only_affixes(after))


def _name_relation(handle_slug: str, full: set[str], tokens: list[set[str]]) -> str | None:
    """How the handle relates to the registered name: ``exact`` (the name itself), ``affix`` (the name plus a plain affix), ``fragment`` (the name sits inside a longer,
    different handle), or None (the name is not in the handle at all)."""
    if not handle_slug:
        return None
    found = False
    best: str | None = None
    for name in (f for f in full if len(f) >= 4):
        rest = _remove_once(handle_slug, name)
        if rest is None:
            continue
        found = True
        relation = "exact" if rest == "|" else ("affix" if _affix_only(rest) else "fragment")
        best = relation if best is None or (relation, best) in (("exact", "affix"), ("exact", "fragment"), ("affix", "fragment")) else best
    if best in ("exact", "affix"):
        return best
    if tokens and not found:
        rest = handle_slug
        for variants in tokens:
            hit = next((v for v in sorted(variants, key=len, reverse=True) if len(v) >= 3 and v in rest), None)
            if hit is None:
                return None
            rest = rest.replace(hit, "", 1)
        return "exact" if not rest else ("affix" if _only_affixes(rest) else "fragment")
    return best if found else None


def declaration_confidence(declared_by: str, match: str, site_score: float | None) -> float:
    """Ceiling for a handle-checked profile: how deliberately the company declared it, less for a name+affix handle, scaled by how well the website itself was verified."""
    base = DECLARATION_CONFIDENCE.get(declared_by, DECLARATION_CONFIDENCE["page_body"]) - (0.05 if match == "affix" else 0.0)
    scale = 1.0 if site_score is None else 0.7 + 0.3 * max(0.0, min(1.0, site_score))
    return round(base * scale, 2)


def assess_social(identity: CanonicalIdentity, domain: str, network: str, handle: str, url: str, page: str, *, related: list[dict] | None = None,
                  declared_by: str = "page_body", site_score: float | None = None) -> SocialVerdict:
    """Judge a link found on the verified site from its handle alone (no network)."""
    v = SocialVerdict(network=network, url=url, handle=handle, page=page, decision="unverified", declared_by=declared_by)
    hs = _slug(handle)
    full, tokens = _name_slugs(identity)
    relation = _name_relation(hs, full, tokens)
    own = relation in ("exact", "affix")
    brand = _slug(domain.split(".")[0]) if domain else ""
    brand_rel = None
    if len(brand) >= 4 and brand in hs:
        rest = _remove_once(hs, brand)
        brand_rel = "exact" if rest == "|" else ("affix" if rest is not None and _affix_only(rest) else "fragment")
    brand_match = brand_rel in ("exact", "affix")

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
        v.decision, v.basis, v.match = "accepted", "name_in_handle", relation
        v.reasons = [f"handle '{handle}' carries the company's registered name" + (" with a plain affix" if relation == "affix" else "")]
    elif brand_match:
        v.decision, v.basis, v.match = "accepted", "domain_brand_in_handle", brand_rel
        v.reasons = [f"handle '{handle}' matches the verified website's brand ({domain})"]
    elif relation == "fragment" or brand_rel == "fragment":
        v.decision = "rejected"
        v.reasons = [f"handle '{handle}' only contains the company's name inside a longer one (a fan page, a sister company or another organisation); a name fragment is not a match"]
    else:
        v.reasons = [f"handle '{handle}' does not carry the company's name or the verified domain; linked from the site but not tied to this entity"]
    if v.decision == "accepted":
        v.verification = "linked_from_company_site"
        v.confidence = declaration_confidence(declared_by, v.match or "exact", site_score)
        v.reasons.append(f"linked from the company's verified website ({declared_by.replace('jsonld_sameAs', 'JSON-LD sameAs').replace('_', ' ')}); not verified on the platform itself")
    return v
