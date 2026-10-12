"""Exact-company resolution for records published by third parties about an employer or supplier.

Used for NAV job ads and public-procurement notices. Those records name an organisation; COGNIS may only attach
them to a company when they resolve to that exact legal entity. A name that merely looks similar is never enough.

Resolution order (first decisive rule wins):

1. The record's organisation number equals the company's  → ``exact`` (``org_number``).
2. It equals one of the company's registered establishments (Enhetsregisteret sub-units) → ``exact``
   (``registered_establishment``). NAV ads usually carry the establishment's number, not the main unit's.
3. The register says that number is a sub-unit whose parent is the company → ``exact`` (``subunit_parent``).
4. The number belongs to anything else → ``wrong_company``.
5. No usable number: the employer name must equal the full registered legal name (legal form included when the
   record states one) and be distinctive, and an independent signal must confirm it — the employer's website is the
   company's identity-verified domain, or the work address is a registered address of the company or one of its
   establishments → ``exact`` (score 0.95). A matching name without such confirmation is ``ambiguous``; anything
   else is ``unresolved``.

Only ``exact`` results may be published. Everything else stays an internal, unverified candidate with its reason.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Literal

from ..core.util import fold
from ..security.urls import host_of, normalize_website, registrable_domain
from .model import CanonicalIdentity
from .normalization import LEGAL_SUFFIXES, is_generic_name, normalize_name, normalize_org_number, normalize_street, org_checksum_ok

ResolutionStatus = Literal["exact", "wrong_company", "ambiguous", "unresolved"]
EXACT_SCORE = 1.0
NAME_PLUS_SIGNAL_SCORE = 0.95
MIN_PUBLISH_SCORE = 0.95  # the evidence gate requires at least this for third-party records

ParentLookup = Callable[[str], Awaitable[str | None]]  # parent org number · "" = not a sub-unit · None = could not check


@dataclass
class EmployerResolution:
    status: ResolutionStatus
    score: float
    basis: str | None  # how an exact match was established (published with the record)
    reason: str  # human-readable explanation (kept for rejected candidates)
    record_org_number: str | None = None
    signals: list[str] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        return self.status == "exact" and self.score >= MIN_PUBLISH_SCORE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkAddress:
    street: str | None = None
    postal_code: str | None = None
    municipality: str | None = None


def valid_org_number(value: object) -> str | None:
    org = normalize_org_number(value)
    return org if len(org) == 9 and org_checksum_ok(org) else None


_ORG_IN_ID = re.compile(r"(?<!\d)(\d{3})[\s.]?(\d{3})[\s.]?(\d{3})(?!\d)")


def org_numbers_in(values: Iterable[object]) -> set[str]:
    """Checksum-valid Norwegian organisation numbers in identifier strings ("NO 923 609 016 MVA", "923609016")."""
    out: set[str] = set()
    for value in values:
        for match in _ORG_IN_ID.finditer(str(value or "")):
            number = "".join(match.groups())
            if org_checksum_ok(number):
                out.add(number)
    return out


_SUFFIX_ALIASES = {"a/s": "as", "aksjeselskap": "as", "allmennaksjeselskap": "asa"}


def _unify(name: str | None) -> str:
    """"A/S" is the older spelling of AS; treat both the same before comparing."""
    return re.sub(r"\ba\s*/\s*s\b", "AS", name or "", flags=re.I)


def _legal_suffix(name: str | None) -> str | None:
    tokens = fold(_unify(name)).replace(".", " ").split()
    suffix = tokens[-1] if tokens and tokens[-1] in LEGAL_SUFFIXES else None
    return _SUFFIX_ALIASES.get(suffix or "", suffix)


def exact_legal_name(record_name: str | None, identity: CanonicalIdentity) -> bool:
    """The record names the company by its full registered name (suffix-insensitive comparison, but a stated legal form must agree)."""
    if not record_name or not identity.legal_name:
        return False
    mine, theirs = normalize_name(_unify(identity.legal_name)), normalize_name(_unify(record_name))
    if not theirs or theirs != mine:
        return False
    stated = _legal_suffix(record_name)
    own = _legal_suffix(identity.legal_name) or _SUFFIX_ALIASES.get((identity.legal_form or "").casefold(), (identity.legal_form or "").casefold()) or None
    return stated is None or own is None or stated == own


def _address_key(street: str | None, postal_code: str | None) -> str | None:
    s = normalize_street(street)
    p = "".join(ch for ch in str(postal_code or "") if ch.isdigit())
    return f"{s}|{p}" if s and len(p) == 4 else None


def registered_address_keys(identity: CanonicalIdentity, establishments: Iterable[dict]) -> set[str]:
    keys: set[str] = set()
    addrs = [identity.business_address, identity.postal_address] + [e.get("address") or {} for e in establishments]
    for addr in addrs:
        if not isinstance(addr, dict):
            continue
        for line in addr.get("adresse") or []:
            key = _address_key(line, addr.get("postnummer"))
            if key:
                keys.add(key)
    return keys


async def resolve_employer(
    identity: CanonicalIdentity,
    *,
    record_org_number: object,
    record_name: str | None,
    alt_names: Iterable[str | None] = (),
    record_homepage: str | None = None,
    work_addresses: Iterable[WorkAddress] = (),
    establishments: Iterable[dict] = (),
    verified_domain: str | None = None,
    parent_of: ParentLookup | None = None,
) -> EmployerResolution:
    """Resolve a third-party record's organisation to ``identity`` (see the module docstring)."""
    target = identity.org_number
    establishments = list(establishments)
    sub_orgs = {valid_org_number(e.get("organisation_number")) for e in establishments} - {None}
    org = valid_org_number(record_org_number)
    raw_org = normalize_org_number(record_org_number)

    if org:
        if org == target:
            return EmployerResolution("exact", EXACT_SCORE, "org_number", f"The record states organisation number {org}.", org, ["org_number"])
        if org in sub_orgs:
            return EmployerResolution("exact", EXACT_SCORE, "registered_establishment",
                                      f"The record states {org}, a registered establishment (underenhet) of {target}.", org, ["registered_establishment"])
        # parent_of returns the parent org number, "" when the number is not a registered sub-unit, None when it could not be checked
        parent = await parent_of(org) if parent_of else None
        if parent == target:
            return EmployerResolution("exact", EXACT_SCORE, "subunit_parent",
                                      f"The register lists {org} as an establishment of {target}.", org, ["subunit_parent"])
        if parent is None:
            return EmployerResolution("unresolved", 0.0, None, f"The record states {org}; whether it is an establishment of {target} could not be checked.", org)
        return EmployerResolution("wrong_company", 0.0, None,
                                  f"The record states organisation number {org}, which belongs to a different organisation" +
                                  (f" (an establishment of {parent})." if parent else "."), org)

    names = [n for n in [record_name, *alt_names] if n]
    note = f" (the stated number {raw_org} is not a valid organisation number)" if raw_org else ""
    if not any(exact_legal_name(n, identity) for n in names):
        mine = normalize_name(_unify(identity.legal_name))
        if any(normalize_name(_unify(n)) and mine and (mine in normalize_name(_unify(n)) or normalize_name(_unify(n)) in mine) for n in names):
            return EmployerResolution("ambiguous", 0.0, None, f"The employer name only resembles the registered name and no organisation number is given{note}.")
        return EmployerResolution("unresolved", 0.0, None, f"The employer name does not match the registered name and no organisation number is given{note}.")
    if is_generic_name(identity.legal_name):
        return EmployerResolution("ambiguous", 0.0, None, f"The registered name is too generic to match on name alone and no organisation number is given{note}.")

    signals = ["exact_legal_name"]
    dom = registrable_domain(host_of(normalize_website(record_homepage) or "")) if record_homepage else ""
    if verified_domain and dom and dom == verified_domain:
        signals.append("verified_domain")
    keys = registered_address_keys(identity, establishments)
    if any(_address_key(w.street, w.postal_code) in keys for w in work_addresses if _address_key(w.street, w.postal_code)):
        signals.append("registered_address")
    if len(signals) > 1:
        return EmployerResolution("exact", NAME_PLUS_SIGNAL_SCORE, "+".join(signals),
                                  "Exact registered name confirmed by " + " and ".join(s.replace("_", " ") for s in signals[1:]) + ".", None, signals)
    munis = {fold(identity.municipality)} | {fold((e.get("address") or {}).get("kommune")) for e in establishments}
    same_muni = any(fold(w.municipality) in munis for w in work_addresses if w.municipality)
    return EmployerResolution("ambiguous", 0.0, None,
                              "The employer name equals the registered name" + (" and the municipality matches" if same_muni else "") +
                              f", but no organisation number, verified website or registered address confirms it{note}.", None, signals)
