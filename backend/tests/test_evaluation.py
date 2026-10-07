"""Evaluation-style scenarios (spec §'15 evaluation-style tests') run fully offline."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from conftest import absence, claims, research, run

from app.competition.changes import compat_profile, diff_profile
from app.competition.envelope import build_envelope, validate_envelope
from app.testing.fixtures import company_page, verified_site

AUTO = "810359862"
GROUP_CHILD = "810363142"
DELETED = "810324562"


def test_01_same_name_company_never_published(net) -> None:  # noqa: ANN001
    """The registry-listed domain belongs to a same-named company with another org number."""
    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", "923609016", jobs=["Selger"]))
    rec = run(research(net, AUTO))
    assert not claims(rec, "official_website") and not claims(rec, "job_posting")
    assert rec["modules"]["website"]["state"] == "ambiguous"
    assert absence(rec, "official_website")["availability"] == "ambiguous"


def test_02_parent_and_subsidiary_from_group_register(net) -> None:  # noqa: ANN001
    rec = run(research(net, GROUP_CHILD))
    parent = claims(rec, "parent_company")
    assert parent and parent[0]["value"] == "STEPHAN INVEST AS" and parent[0]["attributes"]["organisation_number"] == "953506955"


def test_03_stale_parked_website_not_published(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", {"/": "<html><head><title>Domenet er til salgs</title></head><body>This domain is for sale</body></html>"})
    rec = run(research(net, AUTO))
    assert not claims(rec, "official_website") and rec["modules"]["website"]["state"] != "available"


def test_04_registry_conflict_live_wins(net) -> None:  # noqa: ANN001
    bulk_row = {"organisation_number": AUTO, "name": "AUTOBJØRN A/S", "legal_form": "AS", "employees": 9, "municipality": "OSLO", "industry_code": "95.310"}
    rec = run(research(net, AUTO, bulk_row=bulk_row, bulk_meta={"source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/lastned", "content_sha256": "x" * 64}))
    emp = claims(rec, "registered_employees")[0]
    assert emp["value"] == 12 and emp["conflict"] and emp["conflict"]["resolution"] == "official_registry_live"
    env = build_envelope(rec, run_id="t")
    assert env.get("conflicts") and not validate_envelope(env)


def test_05_robots_blocked_source_is_blocked_not_missing(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO), robots="User-agent: *\nDisallow: /")
    rec = run(research(net, AUTO))
    assert rec["modules"]["website"]["state"] == "blocked"
    assert absence(rec, "official_website")["availability"] == "blocked"
    assert claims(rec, "revenue")  # other sources unaffected


def test_06_checked_zero_establishments_is_a_real_zero(net) -> None:  # noqa: ANN001
    rec = run(research(net, DELETED))
    count = claims(rec, "registered_establishment_count")
    assert count and count[0]["value"] == 0 and count[0]["availability"] == "available"


def test_07_unsafe_registry_website_never_fetched(net) -> None:  # noqa: ANN001
    entity = json.loads((Path(__file__).parent / "fixtures" / "brreg" / f"{AUTO}_enhet.json").read_text(encoding="utf-8"))
    entity["hjemmeside"] = "http://127.0.0.1:8080/admin"
    net.add_json(f"https://data.brreg.no/enhetsregisteret/api/enheter/{AUTO}", entity)
    rec = run(research(net, AUTO))
    assert not any("127.0.0.1" in u for u in net.requests)
    assert not claims(rec, "official_website")


def test_08_repeated_refresh_is_idempotent(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO))
    a = run(research(net, AUTO))
    b = run(research(net, AUTO))
    assert diff_profile(compat_profile(a), compat_profile(b)) == []
    ids = lambda r: sorted(e["id"] for e in r["evidence"])  # noqa: E731
    assert ids(a) == ids(b)


def test_09_material_change_detected_with_full_provenance(net) -> None:  # noqa: ANN001
    a = run(research(net, AUTO))
    entity = json.loads((Path(__file__).parent / "fixtures" / "brreg" / f"{AUTO}_enhet.json").read_text(encoding="utf-8"))
    entity["antallAnsatte"] = 15
    net.add_json(f"https://data.brreg.no/enhetsregisteret/api/enheter/{AUTO}", entity)
    b = run(research(net, AUTO))
    changes = diff_profile(compat_profile(a), compat_profile(b))
    assert [c["field"] for c in changes] == ["registry.employees"]
    c = changes[0]
    assert c["old_value"] == 12 and c["new_value"] == 15 and c["source_url"] and c["old_content_sha256"] != c["new_content_sha256"]


def test_10_missing_llm_key_degrades_gracefully(net) -> None:  # noqa: ANN001
    rec = run(research(net, AUTO, provider=None))
    assert rec["summary"]["method"] == "deterministic_template" and rec["summary"]["text"]
    assert claims(rec, "revenue") and rec["terminal_status"] == "completed"


def test_11_timeout_is_terminal_and_isolated(net) -> None:  # noqa: ANN001
    net.fail("https://www.autobjorn.no", "timeout")
    net.fail("https://autobjorn.no", "timeout")
    rec = run(research(net, AUTO))
    assert rec["terminal_status"] == "completed" and rec["modules"]["website"]["state"] in ("failed", "blocked")
    assert claims(rec, "ceo")


def test_12_malformed_llm_json_never_breaks_research(net) -> None:  # noqa: ANN001
    from app.providers.fake_provider import FakeProvider

    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO))
    rec = run(research(net, AUTO, provider=FakeProvider(malformed=True)))
    assert rec["terminal_status"] == "completed"
    assert any(e["stage"].startswith("llm:") for e in rec["errors"])
    assert rec["summary"]["method"] == "deterministic_template"
    desc = claims(rec, "business_description")
    assert desc and desc[0]["extraction_method"] != "llm_quote_verified"  # deterministic paragraph instead


def test_13_wrong_domain_search_results_are_not_evidence(net, settings) -> None:  # noqa: ANN001
    from app.config import override_settings

    override_settings(settings.model_copy(update={"tavily_api_key": "tvly-test-key-0000000000"}))
    entity = json.loads((Path(__file__).parent / "fixtures" / "brreg" / f"{AUTO}_enhet.json").read_text(encoding="utf-8"))
    entity.pop("hjemmeside", None)
    net.add_json(f"https://data.brreg.no/enhetsregisteret/api/enheter/{AUTO}", entity)

    def tavily(request: httpx.Request) -> httpx.Response | None:
        if request.url.host != "api.tavily.com":
            return None
        assert request.method == "POST" and request.headers["authorization"].startswith("Bearer tvly-")
        return httpx.Response(200, json={"results": [
            {"url": "https://www.proff.no/selskap/autobjorn", "title": "AUTOBJØRN A/S - Proff", "content": "Org nr 810 359 862", "score": 0.9},
            {"url": "https://autobjorn-bil.no/", "title": "Autobjørn bil", "content": "AUTOBJØRN", "score": 0.7}]})

    net.handlers.append(tavily)
    net.add_site("autobjorn-bil.no", {"/": company_page("Autobjørn bil", "<p>Autobjørn bil – bruktbiler i Bergen siden 2010. Vi selger biler.</p>",
                                                        footer="Autobjørn Bil AS · Org.nr. 923 609 016")})
    rec = run(research(net, AUTO))
    assert not claims(rec, "official_website")
    assert not any("proff.no" in u for u in net.requests if "tavily" not in u)  # directories are never fetched as company sites
    assert all(e["source_class"] != "search_discovery" for e in rec["evidence"])


def test_14_english_site_verified_by_org_number(net) -> None:  # noqa: ANN001
    pages = {"/": company_page("Autobjorn – car dealer", "<h1>Welcome</h1><p>Autobjorn sells and services cars in Oslo. We have served drivers since 1968 with care.</p>",
                               footer="AUTOBJØRN A/S · Org. no. 810 359 862", links=[("/about", "About us")], lang="en"),
             "/about": company_page("About us", "<p>Autobjorn sells and services cars in Oslo. We have served drivers since 1968 with care and expertise.</p>",
                                    footer="AUTOBJØRN A/S · Org. no. 810 359 862", lang="en")}
    net.add_site("autobjorn.no", pages)
    rec = run(research(net, AUTO))
    site = claims(rec, "official_website")
    assert site and "org_number_on_site" in rec["website"]["audit"]["signals"]


def test_15_deleted_company_status_and_no_invented_financial_zero(net) -> None:  # noqa: ANN001
    rec = run(research(net, DELETED))
    status = claims(rec, "registration_status")[0]
    assert status["value"] == "deleted"
    rev = claims(rec, "revenue")
    assert not rev and absence(rec, "revenue")["availability"] == "not_available"  # missing revenue is not 0
    env = build_envelope(rec, run_id="t")
    assert next(c for c in env["claims"] if c["field"] == "revenue")["value"] is None


def test_unknown_org_number_still_terminal(net) -> None:  # noqa: ANN001
    rec = run(research(net, "923609016"))
    env = build_envelope(rec, run_id="t")
    assert env["run"]["terminal_status"] in ("completed", "failed") and env["claims"] and not validate_envelope(env)
    assert env["claims"][0]["availability"] in ("not_available", "failed", "blocked")


def test_envelope_contract_shape(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO, jobs=["Bilselger"]))
    env = build_envelope(run(research(net, AUTO)), run_id="r1")
    assert set(env) >= {"organisation_number", "run", "claims", "evidence", "changes", "errors", "operations"}
    assert set(env["run"]) == {"run_id", "started_at", "completed_at", "terminal_status"}
    assert set(env["operations"]) >= {"requests", "runtime_ms", "third_party_cost_usd"}
    for c in env["claims"]:
        assert {"field", "value", "availability", "confidence", "evidence_ids"} <= set(c)
    for e in env["evidence"]:
        assert {"id", "source_url", "source_class", "retrieved_at", "content_sha256", "claim_span"} <= set(e)
    assert not validate_envelope(env)
    rev = [c for c in env["claims"] if c["field"] == "revenue"]
    assert rev and all(c.get("reporting_period") for c in rev) and sum(1 for c in rev if c["temporal"] == "current") == 1


def test_batch_one_envelope_per_input_and_budget_exhaustion(tmp_path, settings) -> None:  # noqa: ANN001
    from app.competition.batch import BatchConfig, run_batch
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database
    from app.testing.fixtures import FixtureNetwork, build_synthetic_universe

    rows = [json.loads(line) for line in (Path(__file__).parent / "fixtures" / "entry-companies.jsonl").read_text(encoding="utf-8").splitlines()[:40]]
    net = FixtureNetwork()
    build_synthetic_universe(net, rows)
    orgs = tmp_path / "orgs.txt"
    orgs.write_text("\n".join(r["organisation_number"] for r in rows), encoding="utf-8")
    bulk = tmp_path / "bulk.jsonl"
    bulk.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    cfg = BatchConfig(organisations=str(orgs), bulk=str(bulk), output=str(tmp_path / "env.jsonl"), profiles_output=str(tmp_path / "p.jsonl"),
                      report=str(tmp_path / "r.json"), run_id="t", expected_count=40, max_requests=60, transport=net.transport(), provider=FakeProvider(),
                      use_provider_override=True, db=Database(":memory:"), workers=4)
    report = asyncio.run(run_batch(cfg, settings))
    envs = [json.loads(line) for line in (tmp_path / "env.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(envs) == 40 and report["validation"]["passed"]
    assert report["operations"]["requests"] <= 60
    assert any(e["state"] == "budget_exhausted" or any(m["state"] == "budget_exhausted" for m in e["modules"].values()) for e in envs)
    assert all(any(c["field"] == "legal_name" and c["availability"] == "available" for c in e["claims"]) for e in envs)  # bulk facts survive exhaustion


def test_refresh_replay_fixture_qualifies() -> None:
    from app.competition.refresh import replay

    manifest = json.loads((Path(__file__).parent / "fixtures" / "refresh-snapshots.json").read_text(encoding="utf-8"))
    report = asyncio.run(replay(manifest))
    assert report["qualification_passed"] and report["false_positive"] == 0 and report["recall"] == 1.0
