"""What the hiring research actually established — never "not hiring" from missing data.

Every hiring source is reported as checked / unavailable / incomplete, and the run gets exactly one outcome:

* ``verified``            at least one verified, current opening (other sources that could not be checked are listed as a caveat);
* ``none_found``          the sources were checked and returned no verified opening. Says nothing about whether the company is hiring;
* ``source_unavailable``  a source that could hide openings could not be reached or read (timeout, refusal, robots.txt): no conclusion;
* ``incomplete``          the research did not get to check them (no verified website, budget or time limit, partly built index).

A zero count is only ever published from the company's own explicit "no open positions" statement, and not while a source was unavailable.
"""
from __future__ import annotations

from typing import Any

from ..config import Settings
from ..connectors.nav import MODULE as NAV_MODULE

OUTCOMES = ("verified", "none_found", "source_unavailable", "incomplete")
WHY = {"timeout": "timed out", "network": "connection failed", "server_error": "server error", "rate_limited": "rate limited", "blocked": "access refused",
       "robots_disallowed": "robots.txt does not allow access, which is respected", "client_error": "request refused", "too_large": "response too large",
       "invalid_content": "unreadable response", "unsafe_url": "address not allowed", "budget_exhausted": "request budget used up"}


def _check(cid: str, name: str, state: str, note: str, *, required: bool = True) -> dict[str, Any]:
    return {"id": cid, "name": name, "state": state, "note": note, "required": required}


def _why(classification: str) -> str:
    return WHY.get(classification, classification.replace("_", " "))


def company_checks(st: Any) -> list[dict[str, Any]]:
    crawl, jobs = st.crawl, getattr(st, "company_jobs", None)
    web = st.modules.get("website")
    if crawl is None or not crawl.verified:
        blocked = web is not None and web.state in ("blocked", "failed")
        note = (("The company website could not be read" + (f" ({web.note})" if web is not None and web.note else "") + ", so its careers pages were not checked.") if blocked
                else "No identity-verified company website, so its careers pages were not checked.")
        return [_check("careers", "Company careers pages", "unavailable" if blocked else "incomplete", note)]
    if jobs is None:
        return [_check("careers", "Company careers pages", "incomplete", "The careers pages were not checked in this run.")]
    checks = []
    for kind, cid, name, ok_note in (("careers", "careers", "Company careers pages", "Careers page read." if jobs.careers_found else "The verified website links no careers page."),
                                     ("job_board", "job_board", "Linked job boards", "Linked job board read.")):
        failed = [f for f in jobs.failures if f["kind"] == kind]
        if failed:
            checks.append(_check(cid, name, "unavailable", "; ".join(f"{f['name']}: {_why(f['classification'])}" for f in failed) + "."))
        elif kind == "careers" or any(m.module == "jobs_ats" for m in jobs.modules):
            checks.append(_check(cid, name, "checked", ok_note))
    if jobs.incomplete:
        checks.append(_check("careers_budget", "Company careers pages", "incomplete", "; ".join(jobs.incomplete).capitalize() + "."))
    return checks


def nav_check(st: Any, settings: Settings) -> dict[str, Any] | None:
    if not settings.enable_nav_jobs:
        return None
    mod = st.modules.get(NAV_MODULE)
    name = "NAV Arbeidsplassen"
    if mod is None:
        return _check("nav", name, "incomplete", "NAV Arbeidsplassen was not checked in this run.")
    if mod.state == "not_applicable":  # enabled, but there is no job-ad index in this context: NAV was not consulted
        return _check("nav", name, "incomplete", "NAV Arbeidsplassen was not consulted (no job-ad index in this run).")
    if mod.state in ("failed", "blocked", "not_available"):
        return _check("nav", name, "unavailable", mod.note or "NAV Arbeidsplassen could not be checked.")
    value = mod.value or {}
    if value.get("unreadable"):
        return _check("nav", name, "incomplete", mod.note or "Some NAV ads could not be checked.")
    if value.get("index_fresh") is False:
        return _check("nav", name, "incomplete", "The NAV ad index is still catching up with the feed or was synced long ago, so recent ads may be missing.")
    return _check("nav", name, "checked", "NAV ads checked against the organisation's exact identity.")


def discovery_check(st: Any) -> dict[str, Any] | None:
    mod = st.modules.get("job_discovery")
    if mod is None or mod.state == "not_applicable":
        return None
    name = "Web search for job pages"
    if mod.state in ("failed", "blocked"):
        return _check("discovery", name, "unavailable", mod.note or "Web search was unavailable.", required=False)
    return _check("discovery", name, "checked", mod.note or "Search results were verified before use.", required=False)


def _names(items: list[dict[str, Any]]) -> str:
    names = list(dict.fromkeys(c["name"] for c in items))
    return ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else names[0]


def assess(st: Any, settings: Settings, *, current: int, zero_stated: bool) -> dict[str, Any]:
    checks = company_checks(st)
    for extra in (nav_check(st, settings), discovery_check(st)):
        if extra:
            checks.append(extra)
    bad = [c for c in checks if c["required"] and c["state"] in ("unavailable", "incomplete")]
    unavailable = [c for c in bad if c["state"] == "unavailable"]
    checked = [c for c in checks if c["state"] == "checked"]
    if current > 0:
        outcome = "verified"
        caveat = f"{_names(bad)} could not be fully checked, so there may be further openings." if bad else None
        message = f"{current} verified current opening{'' if current == 1 else 's'}." + (f" {caveat}" if caveat else "")
    elif unavailable:
        outcome, caveat = "source_unavailable", None
        message = (f"{_names(unavailable)} could not be checked ({'; '.join(c['note'].rstrip('.') for c in unavailable)}). "
                   "This is not evidence that the company has no openings.")
        if zero_stated:
            message += " The company's careers page states that it has no open positions, but that is not a complete picture."
    elif bad or getattr(st, "timed_out", False):
        outcome, caveat = "incomplete", None
        why = "; ".join(c["note"].rstrip(".") for c in bad) or "the per-company time limit was reached"
        message = f"Hiring research is incomplete: {why}. This is not evidence that the company has no openings."
    elif checked:
        outcome, caveat = "none_found", None
        message = (f"No verified openings found in the sources checked ({_names(checked)}). This does not mean the company is not hiring."
                   if not zero_stated else
                   "The company's careers page states that it has no open positions. Other sources may still list openings.")
    else:
        outcome, caveat = "incomplete", None
        message = "No hiring source could be checked. This is not evidence that the company has no openings."
    return {"outcome": outcome, "message": message, "caveat": caveat, "checks": checks, "current": current,
            "zero_stated": zero_stated and outcome == "none_found"}


def drop_zero_count(observations: list[Any], outcome: dict[str, Any]) -> list[Any]:
    """A published "0 open positions" is removed whenever the research could not look everywhere (it would read as "not hiring")."""
    if outcome["outcome"] in ("source_unavailable", "incomplete"):
        return [o for o in observations if not (o.field == "open_positions_count" and o.value == 0)]
    return observations
