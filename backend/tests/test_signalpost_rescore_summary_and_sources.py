"""Signalpost re-scoring: (1) the summary opens with a source-attributed buyer-relevant fact, never a registry-field repetition, with no LLM; (2) in a keyless
competition run the verified site's news and careers pages are read, published only when verified, and an unavailable source never becomes "nothing found"."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import research
from test_free_sources import AUTO
from test_signalpost_rescore_identity import ALFHEIM_NAME, ALFHEIM_ORG, housing_net, portal_site

from app.agent import buyer_signal
from app.agent.orchestrator import _opens_with_registry_fields
from app.competition.envelope import build_envelope
from app.config import Settings, override_settings
from app.evidence.gate import publish
from app.evidence.models import Observation
from app.identity.model import CanonicalIdentity
from app.providers.fake_provider import FakeProvider
from app.testing.fixtures import FixtureNetwork, verified_site

NAME = "AUTOBJØRN A/S"


@pytest.fixture
def competition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The official evaluator run: competition mode, keyless (no model, no search key, even if keys leak in through the environment)."""
    for name, value in (("TAVILY_API_KEY", "tvly-leaked"), ("GROQ_API_KEY", "gsk_leaked"), ("LLM_PROVIDER", "groq"), ("GROQ_MODEL", "x")):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("COGNIS_KEYLESS", "1")
    s = Settings(_env_file=None, app_env="test", run_mode="competition", data_dir=tmp_path / "data", retry_base_delay_seconds=0, retry_max_delay_seconds=1,
                 brreg_account_copies_min_interval_seconds=0, ted_min_interval_seconds=0, nav_min_interval_seconds=0)
    override_settings(s)
    return s


def site_net(*, jobs: list[str] | None = None, robots: str | None = None, fail: list[tuple[str, str]] | None = None) -> FixtureNetwork:
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site("autobjorn.no", verified_site(NAME, AUTO, jobs=jobs), robots=robots)
    for prefix, kind in fail or []:
        net.fail(prefix, kind)
    return net


def run(net: FixtureNetwork, org: str = AUTO, **kw: Any) -> dict[str, Any]:
    return asyncio.run(research(net, org, provider=kw.pop("provider", None), **kw))


def published(rec: dict[str, Any], *fields: str) -> list[dict[str, Any]]:
    return [c for c in rec["claims"] if c["availability"] == "available" and c["field"] in fields]


# ------------------------------------------------------------------------------------------------------------- the summary opening (no LLM) --
def test_the_summary_opens_with_a_sourced_revenue_trend_not_registry_fields(competition: Settings) -> None:
    rec = run(site_net())
    summary = rec["summary"]
    first = summary["sentences"][0]
    assert summary["method"] == "deterministic_template" and summary["text"].startswith(first["text"])
    assert first["kind"] == "revenue_trend"
    assert "Regnskapsregisteret" in first["text"] and "FY2023" in first["text"] and "FY2025" in first["text"] and "NOK 29.8M" in first["text"] and "NOK 21.8M" in first["text"]
    revenue_evidence = {e for c in published(rec, "revenue") for e in c["evidence_ids"]}
    assert first["evidence_ids"] and set(first["evidence_ids"]) <= revenue_evidence  # the cited evidence is the revenue filings themselves
    assert "is a Norwegian" not in first["text"] and "AUTOBJØRN" not in first["text"] and "Oslo" not in first["text"]
    assert not _opens_with_registry_fields(summary["text"], CanonicalIdentity(org_number=AUTO, legal_name=NAME))


def test_the_registry_sentence_still_follows_the_lead(competition: Settings) -> None:
    summary = run(site_net())["summary"]
    texts = [s["text"] for s in summary["sentences"]]
    assert any("is a Norwegian private limited company" in t for t in texts[1:])


def test_the_envelope_summary_carries_the_same_lead_with_resolvable_evidence(competition: Settings) -> None:
    env = build_envelope(run(site_net()), run_id="t")
    lead = env["synthesis"]["sentences"][0]
    ids = {e["id"] for e in env["evidence"]}
    assert lead["kind"] == "revenue_trend" and lead["evidence_ids"] and set(lead["evidence_ids"]) <= ids


def _obs(**kw: Any) -> Observation:
    base: dict[str, Any] = dict(field="revenue", value=100.0, module="financials", source_id="accounts", source_name="Regnskapsregisteret", source_class="official_annual_accounts",
                                source_url="https://data.brreg.no/regnskapsregisteret/regnskap/810359862", retrieved_at="2026-11-01T00:00:00Z", content_sha256="abc",
                                claim_span="sumDriftsinntekter = 100", extraction_method="structured_api", reporting_period="2025-01-01/2025-12-31", numeric=True,
                                currency="NOK", period_label="FY2025")
    base.update(kw)
    return Observation(**base)


def _claims(*obs: Observation) -> list[Any]:
    return publish(list(obs), "810359862")[0]


def eid(c: Any) -> str:
    return f"ev-{c.field}-{c.reporting_period or c.as_of or ''}"


def test_priority_latest_filed_result_when_only_one_year_exists() -> None:
    claims = _claims(_obs(value=21_800_000.0, claim_span="sumDriftsinntekter = 21800000 NOK"), _obs(field="annual_result", value=568_000.0, claim_span="aarsresultat = 568000 NOK"))
    lead = buyer_signal.lead_signal(claims, None, eid)
    assert lead and lead["kind"] == "latest_financials"
    assert lead["text"].startswith("Regnskapsregisteret's FY2025 filing reports revenue of NOK 21.8M and an annual result of NOK 568k")
    assert len(lead["evidence_ids"]) == 2


def _site_obs(field: str, value: Any, url: str, **kw: Any) -> Observation:
    base: dict[str, Any] = dict(module="website", source_id="website", source_name="Official company website (autobjorn.no)", source_class="company_owned", source_url=url,
                                retrieved_at="2026-11-01T00:00:00Z", content_sha256="abc", claim_span=str(value)[:80], extraction_method="page_paragraph", identity_score=1.2, tier="B")
    base.update(kw)
    return Observation(field=field, value=value, **base)


def test_priority_company_description_then_announcement_then_award_then_hiring() -> None:
    desc = _site_obs("business_description", "AUTOBJØRN A/S selger og reparerer biler i Oslo og har gjort det siden 1968.", "https://autobjorn.no/om-oss")
    news = _site_obs("news_item", "Vi åpner nytt kontor i Bergen", "https://autobjorn.no/nyheter/bergen", as_of="2026-08-14", attributes={"url": "https://autobjorn.no/nyheter/bergen", "page_kind": "news"},
                     extraction_method="article_page")
    award = Observation(field="procurement_award", value="Vedlikehold av kjøretøy", module="procurement", source_id="doffin", source_name="Doffin notice 2026-123", source_class="official_procurement_notice",
                        source_url="https://doffin.no/notices/2026-123", retrieved_at="2026-11-01T00:00:00Z", content_sha256="abc", claim_span="Vedlikehold av kjøretøy", extraction_method="structured_api",
                        as_of="2026-09-02", identity_score=1.0, attributes={"identity_basis": "organisation_number", "buyer_name": "Oslo kommune"})
    jobs = _site_obs("open_positions_count", 2, "https://autobjorn.no/karriere", numeric=True, as_of="2026-11-01", extraction_method="count_of_postings")
    for obs, kind, needle in ((desc, "company_description", "describes the business as"), (news, "company_announcement", "14 August 2026"),
                              (award, "procurement_award", "2 September 2026"), (jobs, "current_hiring", "2 current job posting")):
        lead = buyer_signal.lead_signal(_claims(obs), None, eid)
        assert lead and lead["kind"] == kind and needle in lead["text"], (kind, lead)
        assert lead["evidence_ids"]
    # all four present: the description comes first (company-stated), then the rest in the documented order
    everything = _claims(desc, news, award, jobs)
    assert buyer_signal.lead_signal(everything, None, eid)["kind"] == "company_description"
    assert buyer_signal.lead_signal(_claims(news, award, jobs), None, eid)["kind"] == "company_announcement"
    assert buyer_signal.lead_signal(_claims(award, jobs), None, eid)["kind"] == "procurement_award"
    # a stated zero or a stale / undated item is not a buyer signal
    assert buyer_signal.lead_signal(_claims(_site_obs("open_positions_count", 0, "https://autobjorn.no/karriere", numeric=True, extraction_method="count_of_postings")), None, eid) is None


def test_with_no_verified_buyer_signal_the_summary_says_so_instead_of_dumping_registry_fields(competition: Settings) -> None:
    """A cooperative with no filed accounts and no verified site: the lead states that nothing buyer-relevant was established; the registry sentence follows, not leads."""
    net = housing_net(ALFHEIM_ORG, ALFHEIM_NAME, "ESEK", host="styrerommet.no", pages=portal_site(), address="Hammersborg torg 1", phone="22865500", email="alfheim25-39@styrerommet.no")
    rec = run(net, ALFHEIM_ORG)
    first = rec["summary"]["sentences"][0]
    assert first["kind"] == "no_signal" and first["text"] == buyer_signal.NO_SIGNAL_TEXT and rec["summary"]["text"].startswith("No buyer-relevant signal")
    assert first["evidence_ids"] == []  # an absence has no evidence to cite, and none is invented
    assert not _opens_with_registry_fields(rec["summary"]["text"], CanonicalIdentity(org_number=ALFHEIM_ORG, legal_name=ALFHEIM_NAME))


def test_no_growth_or_commercial_significance_is_invented(competition: Settings) -> None:
    text = run(site_net())["summary"]["text"].lower()
    for word in ("growing", "growth", "leading", "strong", "significant", "expanding", "promising", "opportunity"):
        assert word not in text


def test_an_llm_summary_that_opens_with_registry_fields_is_rejected_and_the_deterministic_lead_is_used(settings: Settings) -> None:
    registry_first = FakeProvider(script={"synthesis": '{"summary": "AUTOBJØRN A/S is a Norwegian company in Oslo with revenue of NOK 21.8M in FY2025."}'})
    rec = run(site_net(), provider=registry_first)
    assert rec["summary"]["method"] == "deterministic_template" and rec["summary"]["text"].startswith("According to its filed accounts")


def test_an_llm_summary_that_leads_with_the_sourced_fact_is_accepted(settings: Settings) -> None:
    good = FakeProvider(script={"synthesis": '{"summary": "Regnskapsregisteret\'s filed accounts show revenue fell from NOK 29.8M in FY2023 to NOK 21.8M in FY2025. AUTOBJØRN A/S is registered in Oslo."}'})
    rec = run(site_net(), provider=good)
    assert rec["summary"]["method"] == "llm_grounded" and rec["summary"]["text"].startswith("Regnskapsregisteret")


# --------------------------------------------------------------------------- keyless competition path: news and careers on a verified site --
def test_the_keyless_competition_run_reads_the_verified_sites_news_and_careers_pages(competition: Settings) -> None:
    net = site_net(jobs=["Mekaniker", "Selger"])
    rec = run(net)
    assert not competition.llm_enabled and not competition.search_enabled
    assert not [u for u in net.requests if "tavily" in u or "groq" in u]
    news = published(rec, "news_item")
    assert len(news) == 1 and news[0]["as_of"] == "2026-08-14"  # a real publication date, from the article page itself
    article = next(e for e in rec["evidence"] if e["id"] == news[0]["evidence_ids"][0])
    assert article["source_url"].endswith("/nyheter/vi-apner-nytt-kontor-i-bergen")  # the article page, not the listing
    jobs = published(rec, "job_posting")
    assert {c["value"] for c in jobs} == {"Mekaniker", "Selger"} and all(c["as_of"] for c in jobs)
    assert [c["value"] for c in published(rec, "open_positions_count")] == [2]
    assert rec["jobs"]["outcome"]["outcome"] == "verified" and rec["jobs"]["outcome"]["zero_stated"] is False
    assert any(u.rstrip("/").endswith("/karriere") for u in net.requests) and any("/nyheter" in u for u in net.requests)


def test_nav_is_incomplete_not_zero_and_the_hiring_outcome_says_so(competition: Settings) -> None:
    rec = run(site_net())
    outcome = rec["jobs"]["outcome"]
    assert outcome["outcome"] == "incomplete" and outcome["zero_stated"] is False
    assert "not evidence that the company has no openings" in outcome["message"]
    assert not published(rec, "open_positions_count")


def test_an_unavailable_careers_page_is_unavailable_not_zero(competition: Settings) -> None:
    rec = run(site_net(jobs=["Mekaniker"], fail=[("https://www.autobjorn.no/karriere", "503"), ("https://autobjorn.no/karriere", "503")]))
    outcome = rec["jobs"]["outcome"]
    assert outcome["outcome"] == "source_unavailable" and outcome["zero_stated"] is False
    assert not published(rec, "open_positions_count", "job_posting")
    assert next(a for a in rec["absences"] if a["field"] == "open_positions_count")["availability"] != "available"


def test_a_robots_blocked_newsroom_is_blocked_not_empty(competition: Settings) -> None:
    rec = run(site_net(robots="User-agent: *\nDisallow: /nyheter"))
    assert not published(rec, "news_item")
    assert rec["news"]["newsroom"]["state"] == "blocked" and "robots.txt" in rec["news"]["newsroom"]["note"]


def test_an_unverified_site_yields_no_news_no_jobs_and_incomplete_research(competition: Settings) -> None:
    """The manager's / portal's site publishes a news page and a careers page of its own; none of it is about the cooperative."""
    net = housing_net(ALFHEIM_ORG, ALFHEIM_NAME, "ESEK", host="styrerommet.no", pages={**portal_site(), "/karriere": "<html><title>Karriere</title><body><h1>Ledige stillinger</h1><p>Utvikler</p></body></html>"},
                      address="Hammersborg torg 1", phone="22865500", email="alfheim25-39@styrerommet.no")
    rec = run(net, ALFHEIM_ORG)
    assert not published(rec, "news_item", "job_posting", "open_positions_count")
    assert rec["jobs"]["outcome"]["outcome"] == "incomplete" and rec["jobs"]["outcome"]["zero_stated"] is False
    assert rec["news"]["newsroom"]["state"] == "not_applicable"
    assert not [u for u in net.requests if "styrerommet.no/karriere" in u or "styrerommet.no/nyheter" in u]  # the portal's other pages are not even fetched


def test_existing_article_date_and_exact_employer_checks_are_unchanged(competition: Settings) -> None:
    """An undated article page and another employer's posting on the company site are still not published."""
    pages = verified_site(NAME, AUTO, jobs=["Mekaniker"])
    pages["/nyheter/vi-apner-nytt-kontor-i-bergen"] = pages["/nyheter/vi-apner-nytt-kontor-i-bergen"].replace('"datePublished": "2026-08-14"', '"dateModified": "2026-08-14"')
    pages["/karriere"] = pages["/karriere"].replace('"name": "AUTOBJØRN A/S"', '"name": "Helt Annet Firma AS"')
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site("autobjorn.no", pages)
    rec = run(net)
    assert not published(rec, "news_item")
    assert not published(rec, "job_posting")
    assert json.dumps(rec["news"]["newsroom"]["rejected"], ensure_ascii=False)  # the rejection and its reason are kept in the diagnostics
