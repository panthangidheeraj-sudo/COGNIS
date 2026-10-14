"""What each research mode is allowed to do — in one place, so the mode label can never drift from what the run really does.

Quick research is the small run: the essential registers (identity, accounts, roles, establishments, group) plus a lean read of the company's own site.
Its caps bound everything *optional* (website pages, newsroom, careers, search); the essential registers are not optional lookups and are never limited by them.
Deep research is the broad run: the full per-company budget, more pages of the site (the ones about the focus first), several follow-up rounds, search
discovery, AI reading of the verified pages and a cross-source check.

The evidence standard is NOT part of the policy. Both modes pass every observation through the same publication gate (``evidence.gate.publish``); a mode
only decides how much gets looked at, never what counts as verified.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from .focus import focus_kinds

QUICK_SITE_PAGES = 3  # pages of the company site Quick reads (homepage included)
QUICK_LLM_CALLS = 1


@dataclass(frozen=True)
class ModePolicy:
    mode: str
    max_requests: int  # optional lookups stop here; the essential registers do not count against it
    max_seconds: float
    max_searches: int
    max_llm_calls: int
    max_site_pages: int
    follow_up_rounds: int
    job_page_search: bool  # search-engine discovery of job pages: always in Deep; in Quick only when the focus is about hiring

    def allows_job_page_search(self, focus: str | None) -> bool:
        return self.job_page_search or "careers" in focus_kinds(focus)

    def limits(self) -> dict[str, int | float | bool]:
        """The budget as it is shown in a run's effort report (read back from the same object that enforced it)."""
        return {"maxRequests": self.max_requests, "maxSeconds": self.max_seconds, "maxSearches": self.max_searches, "maxLlmCalls": self.max_llm_calls,
                "maxSitePages": self.max_site_pages, "followUpRounds": self.follow_up_rounds, "jobPageSearch": self.job_page_search}


def policy_for(settings: Settings, mode: str) -> ModePolicy:
    """The policy for ``quick`` | ``deep`` | ``competition`` | ``registry``. Anything but Quick gets the full per-company budget (registry: no model calls).

    Quick never exceeds the full budget, even if its own limits are configured higher."""
    s = settings
    full = ModePolicy(mode=mode, max_requests=s.per_company_max_requests, max_seconds=s.per_company_max_seconds, max_searches=s.max_searches_per_company,
                      max_llm_calls=s.max_llm_calls_per_company, max_site_pages=s.max_pages_per_site, follow_up_rounds=max(0, s.max_research_rounds), job_page_search=True)
    if mode == "registry":
        return ModePolicy(**{**full.__dict__, "max_llm_calls": 0})
    if mode != "quick":
        return full
    return ModePolicy(mode="quick", max_requests=min(s.quick_max_requests, full.max_requests), max_seconds=min(s.quick_max_seconds, full.max_seconds),
                      max_searches=min(s.quick_max_searches, full.max_searches), max_llm_calls=min(QUICK_LLM_CALLS, full.max_llm_calls),
                      max_site_pages=min(QUICK_SITE_PAGES, full.max_site_pages), follow_up_rounds=min(1, full.follow_up_rounds), job_page_search=False)
