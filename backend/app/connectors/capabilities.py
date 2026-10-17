"""Which free, official source covers each capability a paid business database (Proff) would offer.

COGNIS does not use Proff (a licensed, paid API). Every Proff capability that matters for company research is mapped
here to a free official source that COGNIS already reads, or is marked ``unavailable`` with the reason. An
unavailable capability is left empty in profiles — never estimated, inferred or filled from another source.

``status``: ``covered`` (the free source provides it) · ``partial`` (provides part of it; the limit is stated) ·
``unavailable`` (no free source; not reproduced).
"""
from __future__ import annotations

from typing import Any

PROFF_CAPABILITY_MAP: list[dict[str, Any]] = [
    {"capability": "Company identity: name, organisation number, legal form, status, addresses, industry (NACE), founding date",
     "status": "covered", "sources": ["brreg_entity"], "note": "Enhetsregisteret open API (live), with the open bulk snapshot as fallback."},
    {"capability": "Foretaksregisteret details: share capital, statutory purpose, registration in the Register of Business Enterprises",
     "status": "covered", "sources": ["brreg_entity"], "note": "Exposed by the Enhetsregisteret API for registered enterprises."},
    {"capability": "Registered employee count", "status": "covered", "sources": ["brreg_entity"],
     "note": "As registered (antallAnsatte); missing is reported as missing, never as zero."},
    {"capability": "Contact details: website, e-mail, phone", "status": "covered", "sources": ["brreg_entity", "company_website"],
     "note": "From the register, plus the company's own website after the identity gate verifies it."},
    {"capability": "Board, CEO, chair, auditor, accountant", "status": "covered", "sources": ["brreg_roles"],
     "note": "Enhetsregisteret roles API; people only in their company-role context (birth dates are discarded)."},
    {"capability": "Branches / establishments", "status": "covered", "sources": ["brreg_subunits"], "note": "Registered sub-units (underenheter)."},
    {"capability": "Group structure (parent, subsidiaries)", "status": "partial", "sources": ["brreg_group", "brreg_entity"],
     "note": "Parent and group membership as the register exposes them; ownership shares are not available (see shareholders)."},
    {"capability": "Key financial figures: revenue, operating result, annual result, assets, equity, total liabilities",
     "status": "covered", "sources": ["brreg_accounts"],
     "note": "Regnskapsregisteret open API, each value with its reporting period and the currency the filing states."},
    {"capability": "Multi-year financial history", "status": "partial", "sources": ["brreg_accounts", "brreg_account_copies"],
     "note": "Years the open API returns, plus the list of filed annual-report copies (PDF) per year."},
    {"capability": "Financial ratios (margins, equity ratio)", "status": "covered", "sources": ["brreg_accounts"],
     "note": "Computed only from filed values of the same period and currency; never across currencies."},
    {"capability": "Shareholders and ownership shares", "status": "unavailable", "sources": [],
     "note": "Skatteetaten's shareholder register is released only on formal request; not available at runtime and never inferred."},
    {"capability": "Credit rating, credit score, payment remarks", "status": "unavailable", "sources": [],
     "note": "Proprietary to licensed credit-information providers; no free official equivalent."},
    {"capability": "Industry benchmarks and market statistics", "status": "unavailable", "sources": [],
     "note": "SSB publishes aggregate statistics only; COGNIS uses SSB's classification (municipality → county) and does not produce company-level benchmarks."},
    {"capability": "Register announcements (kunngjøringer)", "status": "partial", "sources": ["brreg_entity", "brreg_roles"],
     "note": "Changes are detected between COGNIS research runs from register snapshots; Brønnøysund's announcement texts are not imported."},
    {"capability": "Job ads", "status": "covered", "sources": ["company_website", "company_ats", "nav_jobs"],
     "note": "Company careers pages and linked job boards, plus NAV Arbeidsplassen ads resolved to the exact organisation."},
]


def capability_summary() -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in PROFF_CAPABILITY_MAP:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"replaces": "Proff.no API (paid, not used)", "counts": counts, "capabilities": PROFF_CAPABILITY_MAP}


def unavailable_capabilities() -> list[str]:
    return [row["capability"] for row in PROFF_CAPABILITY_MAP if row["status"] == "unavailable"]
