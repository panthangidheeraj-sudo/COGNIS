"""Offline network for tests, the smoke test and the benchmark.

``FixtureNetwork`` is an ``httpx`` transport that serves recorded Brønnøysund
responses (``tests/fixtures/brreg``), synthetic register records generated from
universe rows, small company websites, and injected failures (timeouts, 429,
5xx, 403, robots disallow). Nothing here touches the real network.
"""
from __future__ import annotations

import json
import random
import re
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
BRREG_HOST = "data.brreg.no"


class FixtureNetwork:
    def __init__(self) -> None:
        self.json_routes: dict[str, Any] = {}  # exact URL (no query) → body
        self.query_routes: dict[str, Any] = {}  # exact URL incl. query → body
        self.sites: dict[str, dict[str, str]] = {}  # host → path → html
        self.robots: dict[str, str] = {}
        self.failures: list[tuple[str, str]] = []  # (url prefix, kind)
        self.requests: list[str] = []
        self.handlers: list[Callable[[httpx.Request], httpx.Response | None]] = []

    # ---------------------------------------------------------------- setup --
    def add_json(self, url: str, body: Any, *, query: bool = False) -> None:
        (self.query_routes if query else self.json_routes)[url] = body

    def add_site(self, host: str, pages: dict[str, str], *, robots: str | None = None) -> None:
        self.sites[host.lower()] = pages
        if robots is not None:
            self.robots[host.lower()] = robots

    def fail(self, url_prefix: str, kind: str) -> None:
        self.failures.append((url_prefix, kind))

    def load_brreg_probes(self, directory: Path | None = None) -> list[str]:
        directory = directory or FIXTURE_DIR / "brreg"
        orgs = sorted({p.name.split("_")[0] for p in directory.glob("*_enhet.json")})
        for org in orgs:
            def body(kind: str, org: str = org) -> Any:
                path = directory / f"{org}_{kind}.json"
                if not path.exists():
                    return None
                data = json.loads(path.read_text(encoding="utf-8"))
                return None if isinstance(data, dict) and "error" in data and "raw" in data else data
            self.register_company(org, entity=body("enhet"), roles=body("roller"), subunits=body("underenheter"), group=body("konsern"), accounts=body("regnskap"))
        return orgs

    def register_company(self, org: str, *, entity: Any = None, roles: Any = None, subunits: Any = None, group: Any = None, accounts: Any = None,
                         filing_years: list[str] | None = None) -> None:
        base = "https://data.brreg.no"
        if entity is not None:
            self.add_json(f"{base}/enhetsregisteret/api/enheter/{org}", entity)
        if roles is not None:
            self.add_json(f"{base}/enhetsregisteret/api/enheter/{org}/roller", roles)
        if subunits is not None:
            self.add_json(f"{base}/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000", subunits, query=True)
        if group is not None:
            self.add_json(f"{base}/enhetsregisteret/api/konsernstruktur/{org}", group)
        if accounts is not None:
            self.add_json(f"{base}/regnskapsregisteret/regnskap/{org}", accounts)
            years = filing_years
            if years is None and isinstance(accounts, list):
                years = sorted({str((a.get("regnskapsperiode") or {}).get("tilDato", ""))[:4] for a in accounts if a.get("regnskapsperiode")})
            if years:
                self.add_json(f"{base}/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar", [int(y) for y in years if y.isdigit()])

    # ------------------------------------------------------------- transport --
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        for prefix, kind in self.failures:
            if url.startswith(prefix):
                if kind == "timeout":
                    raise httpx.ReadTimeout("fixture timeout", request=request)
                if kind == "network":
                    raise httpx.ConnectError("fixture connection reset", request=request)
                status = {"429": 429, "500": 500, "503": 503, "403": 403, "404": 404}.get(kind, 500)
                headers = {"Retry-After": "0"} if status == 429 else {}
                return httpx.Response(status, headers=headers, text="fixture failure")
        for handler in self.handlers:
            res = handler(request)
            if res is not None:
                return res
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        if host == BRREG_HOST:
            if url in self.query_routes:
                return _json(self.query_routes[url])
            if parsed.query and "overordnetEnhet" in parsed.query:
                return _json({"page": {"totalElements": 0}})  # checked, zero establishments
            plain = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if plain in self.json_routes:
                return _json(self.json_routes[plain])
            if parsed.path.startswith("/enhetsregisteret/api/enheter") and parsed.query:
                return _json(self._search(urllib.parse.parse_qs(parsed.query)))
            return httpx.Response(404, json={"status": 404, "error": "Not Found"})
        if host in ("rdap.norid.no", "ws.geonorge.no", "api.tavily.com"):
            return httpx.Response(404, json={})
        site_host = host.removeprefix("www.")
        if site_host in self.sites or host in self.sites:
            pages = self.sites.get(host) or self.sites[site_host]
            if parsed.path == "/robots.txt":
                robots = self.robots.get(host) or self.robots.get(site_host)
                return httpx.Response(200, text=robots) if robots is not None else httpx.Response(404)
            path = parsed.path or "/"
            html = pages.get(path) or pages.get(path.rstrip("/")) or pages.get(path + "/")
            if html is None:
                return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
            if html.startswith("REDIRECT "):
                return httpx.Response(301, headers={"location": html.split(" ", 1)[1]})
            return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="unknown host in fixture network")

    def _search(self, query: dict[str, list[str]]) -> dict[str, Any]:
        name = (query.get("navn") or [""])[0].casefold()
        rows = []
        for url, body in self.json_routes.items():
            if re.search(r"/enheter/\d{9}$", url) and isinstance(body, dict) and name and name in str(body.get("navn", "")).casefold():
                rows.append(body)
        return {"_embedded": {"enheter": rows[:20]}, "page": {"totalElements": len(rows), "size": 20, "number": 0}}


def _json(body: Any) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(body, ensure_ascii=False).encode(), headers={"content-type": "application/json"})


# ------------------------------------------------------------------ websites --
def company_page(title: str, body: str, *, footer: str = "", links: list[tuple[str, str]] | None = None, jsonld: list[dict] | None = None,
                 description: str = "", lang: str = "nb") -> str:
    nav = "".join(f'<a href="{href}">{text}</a>' for href, text in (links or []))
    ld = "".join(f'<script type="application/ld+json">{json.dumps(item, ensure_ascii=False)}</script>' for item in (jsonld or []))
    meta = f'<meta name="description" content="{description}">' if description else ""
    return (f'<!doctype html><html lang="{lang}"><head><title>{title}</title>{meta}{ld}</head><body><nav>{nav}</nav><main>{body}</main>'
            f"<footer>{footer}</footer></body></html>")


def verified_site(name: str, org: str, *, city: str = "Oslo", jobs: list[str] | None = None, about: str | None = None) -> dict[str, str]:
    spaced = f"{org[:3]} {org[3:6]} {org[6:]}"
    links = [("/om-oss", "Om oss"), ("/kontakt", "Kontakt"), ("/karriere", "Karriere"), ("/nyheter", "Nyheter"),
             ("https://www.linkedin.com/company/" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), "LinkedIn")]
    about_text = about or (f"{name} leverer tjenester innen sin bransje til kunder i hele {city}-regionen. Vi har lang erfaring og et sterkt fagmiljø, "
                           f"og vi hjelper bedrifter med å gjennomføre prosjekter trygt og effektivt.")
    job_items = "".join(f'<li><a href="/karriere/stilling-{i}">{t}</a></li>' for i, t in enumerate(jobs or []))
    postings = [{"@context": "https://schema.org", "@type": "JobPosting", "title": t, "datePosted": "2026-09-20", "validThrough": "2027-01-31",
                 "hiringOrganization": {"@type": "Organization", "name": name}, "jobLocation": {"@type": "Place", "address": {"addressLocality": city}}}
                for t in (jobs or [])]
    footer = f"{name} · Org.nr. {spaced} · {city}"
    return {
        "/": company_page(f"{name} – forside", f"<h1>Velkommen til {name}</h1><p>{about_text}</p>", footer=footer, links=links,
                          description=f"{name} – {about_text[:120]}"),
        "/om-oss": company_page(f"Om oss – {name}", f"<h1>Om oss</h1><p>{about_text}</p>", footer=footer, links=links),
        "/kontakt": company_page(f"Kontakt – {name}", f'<h1>Kontakt</h1><p>Ring oss eller send e-post til <a href="mailto:post@{_domain_for(name)}">post@{_domain_for(name)}</a>.</p>',
                                 footer=footer, links=links),
        "/karriere": company_page(f"Karriere – {name}", f"<h1>Ledige stillinger</h1><ul>{job_items}</ul>" + ("" if jobs else "<p>Vi har ingen ledige stillinger akkurat nå.</p>"),
                                  footer=footer, links=links, jsonld=postings),
        "/nyheter": company_page(f"Nyheter – {name}", '<article><time datetime="2026-08-14">14. august 2026</time><h2>Vi åpner nytt kontor i Bergen og ansetter flere rådgivere</h2></article>',
                                 footer=footer, links=links),
    }


def _domain_for(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a").replace(" as", ""))
    return f"{slug[:24] or 'firma'}.no"


# ------------------------------------------------------- synthetic companies --
def synthetic_entity(row: dict[str, Any], *, website: str | None, email: str | None) -> dict[str, Any]:
    org = row["organisation_number"]
    entity: dict[str, Any] = {
        "organisasjonsnummer": org, "navn": row.get("name") or f"FIRMA {org} AS",
        "organisasjonsform": {"kode": row.get("legal_form") or "AS", "beskrivelse": "Aksjeselskap"},
        "registreringsdatoEnhetsregisteret": "2015-03-02", "stiftelsesdato": "2015-02-20", "registrertIMvaregisteret": True,
        "naeringskode1": {"kode": row.get("industry_code") or "62.010", "beskrivelse": row.get("industry_label") or "Programmeringstjenester"},
        "forretningsadresse": {"adresse": ["Storgata 1"], "postnummer": "0155", "poststed": (row.get("municipality") or "OSLO").upper(), "kommune": (row.get("municipality") or "OSLO").upper(),
                               "kommunenummer": row.get("municipality_number") or "0301", "land": "Norge", "landkode": "NO"},
        "konkurs": bool(row.get("bankrupt")), "underAvvikling": bool(row.get("liquidating")), "underTvangsavviklingEllerTvangsopplosning": False,
        "registrertIForetaksregisteret": True, "erIKonsern": False, "institusjonellSektorkode": {"kode": "2100", "beskrivelse": "Private aksjeselskaper mv."},
    }
    if row.get("employees") is not None:
        entity["antallAnsatte"] = int(row["employees"])
        entity["harRegistrertAntallAnsatte"] = True
    else:
        entity["harRegistrertAntallAnsatte"] = False
    if row.get("latest_submitted_accounts"):
        entity["sisteInnsendteAarsregnskap"] = str(row["latest_submitted_accounts"])
    if website:
        entity["hjemmeside"] = website
    if email:
        entity["epostadresse"] = email
    return entity


def synthetic_roles(seed: int) -> dict[str, Any]:
    rnd = random.Random(seed)
    first = ["Kari", "Ola", "Ingrid", "Lars", "Nora", "Erik", "Sofie", "Henrik", "Maja", "Jonas"]
    last = ["Nordmann", "Hansen", "Johansen", "Olsen", "Larsen", "Andersen", "Berg", "Haugen", "Dahl", "Lie"]

    def person(i: int) -> dict[str, Any]:
        return {"fornavn": rnd.choice(first), "etternavn": rnd.choice(last) + ("" if i else "")}

    return {"rollegrupper": [
        {"type": {"kode": "DAGL", "beskrivelse": "Daglig leder/ adm.direktør"}, "sistEndret": "2023-05-01",
         "roller": [{"type": {"kode": "DAGL", "beskrivelse": "Daglig leder/ adm.direktør"}, "person": {"navn": person(0)}, "avregistrert": False, "fratraadt": False}]},
        {"type": {"kode": "STYR", "beskrivelse": "Styre"}, "sistEndret": "2024-06-11",
         "roller": [{"type": {"kode": "LEDE", "beskrivelse": "Styrets leder"}, "person": {"navn": person(1)}, "avregistrert": False, "fratraadt": False},
                    {"type": {"kode": "MEDL", "beskrivelse": "Styremedlem"}, "person": {"navn": person(2)}, "avregistrert": False, "fratraadt": False}]},
    ]}


def synthetic_accounts(org: str, seed: int, *, years: int = 2) -> list[dict[str, Any]]:
    rnd = random.Random(seed)
    out = []
    revenue = rnd.randint(2, 400) * 1_000_000
    for i in range(years):
        year = 2025 - i
        rev = int(revenue * (1 - 0.08 * i))
        op = int(rev * rnd.uniform(-0.05, 0.15))
        res = int(op * 0.78)
        assets = int(rev * rnd.uniform(0.4, 1.1))
        equity = int(assets * rnd.uniform(0.1, 0.6))
        out.append({
            "id": seed * 10 + i, "journalnr": f"{year + 1}{seed:06d}", "regnskapstype": "SELSKAP", "valuta": "NOK",
            "virksomhet": {"organisasjonsnummer": org, "organisasjonsform": "AS", "morselskap": False},
            "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
            "revisjon": {"ikkeRevidertAarsregnskap": False, "fravalgRevisjon": False},
            "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": float(rev)}, "driftskostnad": {"sumDriftskostnad": float(rev - op)},
                                                            "driftsresultat": float(op)},
                                         "ordinaertResultatFoerSkattekostnad": float(int(op * 0.98)), "aarsresultat": float(res)},
            "eiendeler": {"sumEiendeler": float(assets)},
            "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": float(equity)}, "gjeldOversikt": {"sumGjeld": float(assets - equity)}},
        })
    return out


def build_synthetic_universe(net: FixtureNetwork, rows: list[dict[str, Any]], *, seed: int = 7) -> dict[str, dict[str, Any]]:
    """Register synthetic records for each row with a realistic mix of situations.

    Returns {org: scenario} so a smoke test can check behaviour per scenario.
    """
    rnd = random.Random(seed)
    scenarios: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows):
        org = row["organisation_number"]
        roll = rnd.random()
        name = row.get("name") or f"FIRMA {org} AS"
        domain = _domain_for(name)
        scenario: dict[str, Any] = {"kind": "registry_only", "domain": None}
        website = email = None
        if roll < 0.35:
            scenario = {"kind": "verified_site", "domain": domain}
            website = f"www.{domain}"
            net.add_site(domain, verified_site(name, org, jobs=["Prosjektleder", "Rådgiver"] if i % 3 == 0 else []))
        elif roll < 0.42:
            scenario = {"kind": "email_domain_site", "domain": domain}
            email = f"post@{domain}"
            net.add_site(domain, verified_site(name, org))
        elif roll < 0.48:
            scenario = {"kind": "wrong_company_site", "domain": domain}
            website = f"www.{domain}"
            other = "923609016" if org != "923609016" else "974760673"
            net.add_site(domain, verified_site("ANNET FIRMA AS", other))
        elif roll < 0.52:
            scenario = {"kind": "parked_site", "domain": domain}
            website = domain
            net.add_site(domain, {"/": "<html><head><title>Domenet er til salgs</title></head><body>This domain is for sale</body></html>"})
        elif roll < 0.56:
            scenario = {"kind": "robots_blocked_site", "domain": domain}
            website = domain
            net.add_site(domain, verified_site(name, org), robots="User-agent: *\nDisallow: /")
        elif roll < 0.60:
            scenario = {"kind": "timeout_site", "domain": domain}
            website = domain
            net.fail(f"https://{domain}", "timeout")
        elif roll < 0.63:
            scenario = {"kind": "accounts_5xx", "domain": None}
            net.fail(f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}", "503")
        elif roll < 0.65:
            scenario = {"kind": "roles_429", "domain": None}
            net.fail(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}/roller", "429")
        elif roll < 0.67:
            scenario = {"kind": "not_in_register", "domain": None}
            scenarios[org] = scenario
            continue
        net.register_company(org, entity=synthetic_entity(row, website=website, email=email), roles=synthetic_roles(seed + i),
                             accounts=synthetic_accounts(org, seed + i) if row.get("legal_form") in ("AS", "ASA", None) and i % 5 else [],
                             subunits={"_embedded": {"underenheter": []}, "page": {"totalElements": 0}})
        scenarios[org] = scenario
    return scenarios
