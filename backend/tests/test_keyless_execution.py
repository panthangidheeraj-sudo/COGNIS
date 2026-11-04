"""A genuine keyless run: no GROQ/TAVILY key, no .env, no model. Every valid organisation still gets its own envelope and profile, built deterministically
from verified evidence, with explicit statuses wherever a source gave nothing. Structurally valid is not the same as fully researched."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from conftest import research
from test_free_sources import AUTO

from app.competition.envelope import AVAILABILITY_STATES, build_envelope, validate_envelope
from app.config import Settings, override_settings, validate_configuration
from app.testing.fixtures import FixtureNetwork, build_synthetic_universe, verified_site

NAME = "AUTOBJØRN A/S"


@pytest.fixture
def keyless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Keyless settings that real environment variables cannot change: leaked keys are set in the environment on purpose."""
    for name, value in (("TAVILY_API_KEY", "tvly-leaked-from-the-shell"), ("GROQ_API_KEY", "gsk_leaked"), ("LLM_PROVIDER", "groq"), ("GROQ_MODEL", "x"), ("LLM_API_KEY", "k")):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("COGNIS_KEYLESS", "1")
    s = Settings(_env_file=None, app_env="test", data_dir=tmp_path / "data", retry_base_delay_seconds=0, retry_max_delay_seconds=1,
                 brreg_account_copies_min_interval_seconds=0, ted_min_interval_seconds=0, nav_min_interval_seconds=0)
    override_settings(s)
    return s


def test_the_keyless_guard_overrides_keys_from_the_shell_and_from_dotenv(keyless: Settings) -> None:
    assert keyless.cognis_keyless and not keyless.search_enabled and not keyless.llm_enabled
    assert keyless.llm_provider == "none" and keyless.tavily_api_key is None and keyless.groq_api_key is None and keyless.llm_api_key is None
    assert validate_configuration(keyless) == []  # nothing is half-configured, so there is nothing to warn about or to suppress


def test_unset_keys_alone_are_keyless_without_the_guard(tmp_path: Path) -> None:
    s = Settings(_env_file=None, app_env="test", data_dir=tmp_path / "d", tavily_api_key=None, groq_api_key=None)
    assert s.llm_provider == "none" and not s.llm_enabled and not s.search_enabled


def _net() -> FixtureNetwork:
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site("autobjorn.no", verified_site(NAME, AUTO))
    return net


def test_a_keyless_research_run_is_deterministic_evidence_linked_and_never_calls_a_model_or_search(keyless: Settings) -> None:
    net = _net()
    rec = asyncio.run(research(net, AUTO, provider=None))
    assert rec["summary"]["method"] == "deterministic_template" and rec["summary"]["evidence_ids"]
    assert not [u for u in net.requests if "api.tavily.com" in u or "groq.com" in u]
    claims = {c["field"]: c for c in rec["claims"] if c["availability"] == "available"}
    assert "legal_name" in claims and "official_website" in claims and "revenue" in claims
    env = build_envelope(rec, run_id="t")
    assert validate_envelope(env) == [] and env["state"] == "complete"
    assert all(c["availability"] in AVAILABILITY_STATES for c in env["claims"])
    ev = {e["id"] for e in env["evidence"]}
    assert all(i in ev for c in env["claims"] for i in c["evidence_ids"])  # every claim points at evidence that exists
    assert rec["trends"] and "Revenue" in rec["trends"]["text"]  # multi-year trend without any model
    unavailable = [c for c in env["claims"] if c["availability"] != "available"]
    assert all(c.get("note") or c.get("value") is None for c in unavailable)  # a missing value is stated, never filled in


def test_missing_search_is_reported_as_a_limitation_not_as_an_empty_finding(keyless: Settings) -> None:
    rec = asyncio.run(research(_net(), AUTO, provider=None))
    news = rec["news"]["search"]
    assert news["state"] == "not_applicable" and "not configured" in news["note"] and "TAVILY" in news["note"]
    assert rec["modules"]["news_discovery"]["state"] != "available"


def test_an_unreachable_website_keeps_the_company_and_records_the_network_failure(keyless: Settings) -> None:
    net = _net()
    net.fail("https://www.autobjorn.no", "dns")
    net.fail("https://autobjorn.no", "dns")
    rec = asyncio.run(research(net, AUTO, provider=None))
    env = build_envelope(rec, run_id="t")
    assert validate_envelope(env) == [] and any(c["field"] == "legal_name" and c["availability"] == "available" for c in env["claims"])
    site = next(c for c in env["claims"] if c["field"] == "official_website")
    assert site["availability"] != "available" and site["value"] is None
    assert env["modules"]["website"]["state"] in ("source_error", "not_found", "blocked_policy")
    attempt = next(a for a in env["website_attempts"] if a["origin"] == "registry")
    assert attempt["state"] in ("failed", "blocked", "not_available") and attempt["decision"] != "verified"


def test_a_batch_without_keys_emits_one_envelope_and_profile_per_valid_organisation(keyless: Settings, tmp_path: Path) -> None:
    from app.competition.batch import BatchConfig, run_batch
    from app.storage.db import Database

    rows = [json.loads(line) for line in (Path(__file__).parent / "fixtures" / "entry-companies.jsonl").read_text(encoding="utf-8").splitlines()[:12]]
    net = FixtureNetwork()
    build_synthetic_universe(net, rows)
    orgs = tmp_path / "orgs.txt"
    orgs.write_text("\n".join(r["organisation_number"] for r in rows), encoding="utf-8")
    bulk = tmp_path / "bulk.jsonl"
    bulk.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    cfg = BatchConfig(organisations=str(orgs), bulk=str(bulk), output=str(tmp_path / "env.jsonl"), profiles_output=str(tmp_path / "p.jsonl"), report=str(tmp_path / "r.json"),
                      run_id="keyless", expected_count=12, transport=net.transport(), db=Database(":memory:"), workers=3)
    report = asyncio.run(run_batch(cfg, keyless))
    envs = [json.loads(line) for line in (tmp_path / "env.jsonl").read_text(encoding="utf-8").splitlines()]
    profiles = [json.loads(line) for line in (tmp_path / "p.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {e["organisation_number"] for e in envs} == {r["organisation_number"] for r in rows} == {p["organisation_number"] for p in profiles}
    assert report["validation"]["passed"] and report["llm"] and not [u for u in net.requests if "tavily" in u or "groq" in u]
    v = report["verification"]
    assert v["companies_submitted"] == v["companies_processed"] == 12 and v["keyless"]["keyless_run"] is True and v["keyless"]["llm_provider"] == "none"
    assert v["claims"]["available"] > 0 and "researched" not in v["claims"]
    # structurally valid is reported separately from researched-beyond-the-register
    assert v["structurally_valid"] is True and 0 <= v["companies_researched_beyond_register"] <= 12
    assert set(v["claims"]["by_availability"]) <= set(AVAILABILITY_STATES)
