"""Company selection: a typed name is only a search term. Research starts for a company the user picked (organisation number), after the
number's format and check digit and the registry identity have been verified — never for a guess such as "the one exact name match"."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.testing.fixtures import verified_site

AUTO = "810359862"
NAME = "AUTOBJØRN A/S"


@pytest.fixture
def client(net, settings):  # noqa: ANN001, ANN201
    from app.api.main import create_app
    from app.api.services import Services
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database

    net.add_site("autobjorn.no", verified_site(NAME, AUTO, jobs=["Bilselger", "Mekaniker"]))
    svc = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    with TestClient(create_app(svc)) as c:
        yield c


def _start(client: TestClient, **body):  # noqa: ANN003, ANN202
    return client.post("/api/research/runs", json={"mode": "quick", **body})


def _researched(net, org: str = AUTO) -> bool:  # noqa: ANN001
    """Did anything go beyond the registry search? (company pages, accounts, roles… are fetched only once research starts.)"""
    return any(f"/enheter/{org}" in u or "autobjorn.no" in u for u in net.requests)


def test_a_name_nobody_registered_is_not_found_and_researches_nothing(client, net) -> None:  # noqa: ANN001
    res = _start(client, query="abc")
    assert res.status_code == 404 and res.json()["code"] == "not_found"
    assert not _researched(net)


@pytest.mark.parametrize("typed", ["autobj", "AUTOBJØRN", "AUTOBJØRN A/S"])  # partial, one exact registry name, exact with legal form
def test_a_typed_name_that_matches_exactly_one_company_still_has_to_be_confirmed(client, net, typed) -> None:  # noqa: ANN001
    """The reported bug: the text equalled one registry name, so that company was researched without the user choosing it."""
    run = _start(client, query=typed).json()
    assert run["status"] == "ambiguous" and "company" not in run
    cands = run["ambiguity"]["candidates"]
    assert [c["orgNumber"] for c in cands] == [AUTO]
    assert "Confirm" in run["ambiguity"]["message"]
    assert not _researched(net)


def test_several_matches_are_listed_and_none_is_chosen(client, net) -> None:  # noqa: ANN001
    run = _start(client, query="bjørn").json()
    assert run["status"] == "ambiguous" and len(run["ambiguity"]["candidates"]) == 2
    assert "Pick the exact company" in run["ambiguity"]["message"]
    assert not _researched(net)


def test_confirming_a_candidate_by_organisation_number_starts_research(client) -> None:  # noqa: ANN001
    run = _start(client, orgNumber=AUTO, query="AUTOBJØRN AS", expectedName=NAME).json()
    assert run["status"] in ("running", "awaiting_confirmation")
    assert run["company"]["orgNumber"] == AUTO and run["company"]["legalName"]


def test_an_organisation_number_typed_directly_is_an_identifier(client) -> None:  # noqa: ANN001
    for typed in (AUTO, "810 359 862"):
        run = _start(client, query=typed).json()
        assert run["status"] in ("running", "awaiting_confirmation") and run["company"]["orgNumber"] == AUTO


@pytest.mark.parametrize("org", ["12345", "8103598621", "81035986x", "810359863"])  # too short, too long, not digits, wrong check digit
def test_a_malformed_organisation_number_is_rejected_before_any_lookup(client, net, org) -> None:  # noqa: ANN001
    before = len(net.requests)
    res = _start(client, orgNumber=org, query="x")
    assert res.status_code in (400, 422) and res.json()["code"] == "invalid"
    assert len(net.requests) == before


def test_a_selection_whose_name_does_not_match_the_registry_is_refused(client) -> None:  # noqa: ANN001
    res = _start(client, orgNumber=AUTO, query="Some Other Company AS", expectedName="Some Other Company AS")
    assert res.status_code == 409 and res.json()["code"] == "ambiguous"
    body = res.json()
    assert body["details"]["orgNumber"] == AUTO and body["details"]["expectedName"] == "Some Other Company AS" and body["details"]["registeredName"]


def test_the_name_check_ignores_case_punctuation_and_the_legal_form(client) -> None:  # noqa: ANN001
    registered = client.get(f"/api/companies/{AUTO}").json()["company"]["legalName"]
    for spelled in (registered, registered.lower(), registered.upper()):
        assert _start(client, orgNumber=AUTO, query=spelled, expectedName=spelled).status_code == 200
