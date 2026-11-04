"""Keyless website discovery: name-derived domain candidates.

When the register lists no website (or the listed site could not be verified) and no search API is configured, the only public, key-free way to find an
official site is to try the domains a company of this name would plausibly own. This module only *proposes* candidates. A candidate is never evidence:
every one goes through the same fetch → identity gate as a search hit (org number, domain holder at Norid, exact name + a second registered identifier).
A domain that merely looks like the company's name is rejected when the page belongs to someone else, and the rejection stays in diagnostics.

Bounded and respectful: at most ``MAX_CANDIDATES`` hosts, one homepage fetch each (robots.txt respected by the shared HTTP client), skipped entirely for
generic names where a name-shaped domain would almost surely belong to another business.
"""
from __future__ import annotations

import re

from ..identity.model import CanonicalIdentity
from ..identity.normalization import ascii_fold, distinctive_tokens, is_generic_name, name_tokens, spell_as
from ..security.urls import registrable_domain

MAX_CANDIDATES = 4
TLDS = ("no", "com")


def _slug(parts: list[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_fold(" ".join(parts)))


def candidate_domains(identity: CanonicalIdentity, *, exclude: set[str] | None = None, limit: int = MAX_CANDIDATES) -> list[str]:
    """Plausible registrable domains for the legal name, best first: the full distinctive name as one word, then hyphenated, then the first word."""
    name = spell_as(identity.legal_name)
    if not name or is_generic_name(name):
        return []
    tokens = name_tokens(name)
    distinct = distinctive_tokens(name)
    if not distinct:
        return []
    slugs: list[str] = []
    for variant in (_slug(tokens), "-".join(filter(None, (re.sub(r"[^a-z0-9]", "", ascii_fold(t)) for t in tokens))), _slug(distinct[:1]) if len(distinct[0]) >= 5 else ""):
        if variant and len(variant) >= 4 and variant not in slugs:
            slugs.append(variant)
    skip = exclude or set()
    out: list[str] = []
    for tld in TLDS:
        for slug in slugs:
            dom = registrable_domain(f"{slug}.{tld}")
            if dom and dom not in skip and dom not in out:
                out.append(dom)
    return out[:limit]
