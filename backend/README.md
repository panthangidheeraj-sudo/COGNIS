# COGNIS backend — Signalpost company research agent

Python 3.11+ · FastAPI · Pydantic v2 · httpx/asyncio · SQLite · BeautifulSoup/lxml · pytest · ruff

This backend does two jobs with one research engine:

1. **Evaluator contract** — given Norwegian organisation numbers, it writes exactly one terminal
   OUTPUT_CONTRACT envelope per company (claims + evidence + changes + errors + operations).
2. **Product API** — it serves the COGNIS frontend (`../API_CONTRACT.md`): profiles, research runs
   with live progress (SSE), library, data sheets, compare, watchlist, exports.

> Source data first, identity second, evidence third, reasoning fourth, synthesis last.
> Never sacrifice exact-company precision for recall.

---

## 1. How it works

```
organisation number
  │
  ├─ 1 IDENTITY   Enhetsregisteret (live API, bulk snapshot as fallback) → canonical identity
  ├─ 2 OFFICIAL   roles · establishments · group structure · annual accounts · filed reports (parallel)
  ├─ 3 WEBSITE    candidates: register's website → registered e-mail domain → establishment sites → web search
  │               each candidate passes the identity gate (org number on site, Norid holder, register link,
  │               legal name, address, phone, e-mail …); a conflicting org number vetoes; parked sites rejected
  ├─ 4 ENRICH     only on a verified site: careers/ATS jobs, news, contact, social profiles;
  │               LLM plans extra page fetches (from a menu Python offers) and reads pages — quotes verified
  ├─ 5 GATE       deterministic publication gate: source URL + retrieval time + hash + exact span + method;
  │               search results never evidence; numbers must be real and periodised; conflicts resolved by
  │               authority then recency and kept; explicit absences (not_available / blocked / ambiguous …)
  └─ 6 SYNTHESIS  LLM summary whose numbers must appear in the published facts (else a template summary)
```

| Layer | Role | Where |
| --- | --- | --- |
| LLM = brain | plans follow-up fetches, reads verified pages, writes summaries/explanations | `app/agent/llm_tasks.py`, `app/agent/prompts.py` |
| Python = control | identity, URL safety, budgets, publication gate, validation | `app/identity`, `app/security`, `app/runtime`, `app/evidence/gate.py` |
| Database = memory | records, facts + versions, evidence, changes, runs, tool calls, cache | `app/storage` |
| Connectors = eyes | Brønnøysund, websites, ATS, Norid, Geonorge, Tavily, licensed sources | `app/connectors` |

Every research run produces one **research record** (`app/agent/record.py`). The evaluator envelope
(`app/competition/envelope.py`), the starter-compatible profile used for change detection
(`app/competition/changes.py`) and the frontend `CompanyProfile` (`app/api/profile_builder.py`) are all
built from that same record.

## 2. Requirements

* Python **3.11 or newer** (`python --version`)
* Internet access to `data.brreg.no` (and to company websites); optional: Groq / Tavily keys
* Node 20+ only if you also run the frontend

## 3. Install (Windows PowerShell — macOS/Linux in brackets)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # [source .venv/bin/activate]
python -m pip install -r requirements-dev.txt
copy .env.example .env              # [cp .env.example .env]
```

If PowerShell refuses to run the activate script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again.

## 4. Configuration (`.env`)

Everything is optional. With no keys at all the agent still uses the official registers and the
websites the register links to.

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `none` (default), `groq`, `openai_compatible`, `fake` (tests) |
| `GROQ_API_KEY`, `GROQ_MODEL` | Groq key and the model you are permitted to use (both required for Groq) |
| `LLM_MIN_INTERVAL_SECONDS` | spacing between LLM calls for low rate-limit plans (e.g. `2.0`) |
| `TAVILY_API_KEY` | web discovery of websites the register does not list (candidates only; free plan = 1,000 searches/month) |
| `MAX_RUN_SECONDS`, `MAX_REQUESTS`, `MAX_EXTERNAL_COST_USD` | hard run budgets (defaults 2700 s / 2000 / $10) |
| `PER_COMPANY_*`, `MAX_PAGES_PER_SITE`, `MAX_LLM_CALLS_PER_COMPANY` | per-company limits |
| `RUN_MODE` | `competition` hides `/docs` and debug endpoints |
| `DATA_DIR` | where SQLite + exports live; **set it outside OneDrive/Dropbox** if the project is in a synced folder |

Keys are read from the environment or `.env` only, are never logged (redaction is enforced and
tested) and are never written to records, envelopes or the database. `.env` is git-ignored.

## 5. One-command run

```powershell
python scripts/run_agent.py --input orgs.txt --output out/envelopes.jsonl
```

`orgs.txt` holds one organisation number per line (JSON / JSONL lists also work). Next to the output
you get `envelopes-report.json` and `envelopes-profiles.jsonl`.

## 6. Evaluator batch contract (starter-kit compatible)

```powershell
python scripts/run_competition_batch.py `
  --organisations orgs.jsonl --bulk enheter.csv `
  --output out/envelopes.jsonl --profiles-output out/profiles.jsonl --report out/run-report.json `
  --run-id my-run --expected-count 100 `
  [--previous-profiles out/old-profiles.jsonl] [--max-requests 2000] [--max-cost-usd 10] `
  [--max-runtime-seconds 2700] [--workers 8] [--resume] [--fresh]
```

* `--bulk` accepts the Brreg CSV, the Signalpost universe JSONL or the Brreg JSON download (`.gz` ok);
  it is optional — the live register is always queried, the snapshot is a fallback and corroboration.
* Exactly one envelope per input, in input order; the run fails (exit 1) only if the completeness
  validator fails. `--resume` with the same `--run-id` continues from the database.
* When the run budget runs low, remaining companies still get terminal envelopes from the bulk
  snapshot with live modules marked `blocked` (`budget_exhausted`).

Envelope (primary keys exactly as OUTPUT_CONTRACT; extra keys are additive):

```json
{"organisation_number": "923609016",
 "run": {"run_id": "…", "started_at": "…", "completed_at": "…", "terminal_status": "completed"},
 "claims": [{"field": "revenue", "value": 120.0, "availability": "available", "confidence": 0.98,
             "evidence_ids": ["ev-…"], "reporting_period": "2024-01-01/2024-12-31", "period_label": "FY2024", "temporal": "current"}],
 "evidence": [{"id": "ev-…", "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/923609016",
               "source_class": "official_annual_accounts", "retrieved_at": "…", "content_sha256": "…",
               "claim_span": "resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter = 120 NOK (…)"}],
 "changes": [], "errors": [],
 "operations": {"requests": 9, "runtime_ms": 2140, "third_party_cost_usd": 0.0},
 "state": "complete", "modules": {"…": {"state": "complete"}}, "synthesis": {"summary": "…"}}
```

Availability is one of `available · not_available · blocked · not_applicable · ambiguous · failed`.
A checked source that has nothing (e.g. zero establishments, no CEO registered) is `available` with
the real value or `not_available` with evidence of the check — never confused with a source that was
not checked or failed.

## 7. Refresh replay (change detection on evaluator-owned bytes)

```powershell
python scripts/run_refresh_replay.py --manifest tests/fixtures/refresh-snapshots.json --output out/refresh-demo.json
```

Result on the starter fixture: 2 expected, 2 observed, 0 false positives, precision 1.0, recall 1.0,
evidence complete, idempotent re-run → `qualification_passed: true`.

## 8. API server + the COGNIS frontend

```powershell
# terminal 1 — backend
cd backend; .venv\Scripts\Activate.ps1
uvicorn app.api.main:app --port 8000

# terminal 2 — frontend (project root)
npm install
npm run dev:live          # Vite on http://localhost:5173, /api proxied to :8000
```

`npm run dev` still runs the frontend on its built-in mock backend. To click through the live UI
without internet, start `python scripts/serve_offline.py` instead of uvicorn (recorded register data).

Besides the frontend contract the API offers: `POST /api/research/company` (one envelope),
`POST /api/research/batch` + `GET /api/runs/{id}`, `GET /api/companies/{org}/evidence|changes|sources`,
`GET /api/health`, `GET /api/metrics`; interactive docs at `/docs` outside competition mode.

## 9. Sources and permissions

See `docs/SOURCES.md` and `sources.yaml`. In short: official Norwegian registers are used directly;
company-owned websites (and the job boards / social pages they link to) only after identity
verification; search results are leads, never evidence; LinkedIn, Proff, Doffin, Patentstyret and NAV
are not scraped — licensed APIs can be enabled with keys, otherwise they report `not_configured`.
robots.txt is respected (unreachable robots.txt ⇒ treated as disallow, RFC 9309).

## 10. Identity and evidence rules (deterministic)

* Identity score = sum of independent signals (`app/identity/match.py`); verified ≥ 0.75, or ≥ 0.60 for
  the site the register itself lists. A different organisation number shown on the site vetoes.
* The publication gate (`app/evidence/gate.py`) rejects anything without source URL, retrieval time,
  exact span or method; search/discovery evidence; website facts without verified identity; numbers that
  are not numbers; financials without a reporting period; LLM text whose quote is not on the page.
* Conflicts: identical values corroborate; different values → most authoritative source class, then most
  recent retrieval; the losing values are kept in `conflict.candidates` with their evidence.
* Financials: company and consolidated (`consolidated_*`) accounts are separate fields; missing ≠ 0.
* **Currency** (e.g. Equinor ASA files in USD): the filing's own `valuta` is the only authority. It travels
  `valuta` → `parse_financial_record` → `Observation.currency/unit` + the evidence span (`… = 67960000000 USD (…)`) →
  claim → profile fact (`value` = unrounded number, `currency`, `unit`, `displayValue` built from that same code) →
  series/section/snapshot/brief/summary/compare/sheet/CSV·JSON·XLSX export (`value`, `raw_value`, `currency`,
  `evidence_excerpt`). The gate refuses a currency label that does not appear in its own evidence span, or a unit that
  disagrees with it. A missing/malformed `valuta` is published as "currency not stated" (number as filed, no label, a
  note) — it is never replaced by NOK. Amounts are **never converted**: growth, ratios, chart axes, ranking and the
  NOK revenue filter only combine amounts that are provably in one currency; otherwise the UI/API says
  "mixed currencies" and shows each amount in its own. `tests/test_currency.py` pins the whole chain.

## 11. Budgets, retries and failures

* One central run budget (requests / cost / runtime) with a finalisation reserve; per-company caps;
  optional enrichment stops at 90 % (`BUDGET_HEADROOM`). Every request is charged before it is sent.
* Retries only for timeouts, connection errors, 429 and 5xx (bounded, jittered backoff, `Retry-After`
  honoured up to the cap); never for 400/401/403/404/410.
* Per-host concurrency limits; Regnskapsregisteret copy endpoint spaced ≥ 2.1 s.
* SSRF protection: http(s) only, standard ports, no credentials in URLs, public addresses only
  (checked again after DNS and on every redirect hop), size and time limits.
* A failure in one source never fails a company; a failure in one company never fails a batch.

## 12. Tests, smoke test, benchmark

```powershell
python -m pytest -q                     # 75 tests, fully offline (fixtures + fake LLM)
ruff check app scripts tests
python scripts/smoke_test.py            # 100 companies, offline, injected failures → out/smoke/smoke-report.md
python scripts/smoke_test.py --live     # the same 100 companies against the real sources
python scripts/benchmark.py --live --count 20
python scripts/inspect_profile.py 923609016     # what was published, what not, and why
```

## 13. Project layout

```
app/agent         orchestrator (bounded research loop), LLM tasks, prompts, research record
app/api           FastAPI app, profile builder, briefs/explain/ask, research runs (SSE), library, sheets, discover, compare/export
app/competition   envelope, batch runner, change detection, refresh replay, input/bulk readers
app/connectors    brreg, website crawler, jobs/ATS, search, norid, geonorge, licensed/optional sources
app/evidence      data model + publication gate
app/extraction    HTML parsing, registry facts, website facts
app/identity      org-number checks, canonical identity, website identity scoring
app/net, runtime, security, storage, providers
scripts/          run_agent, run_competition_batch, run_refresh_replay, smoke_test, benchmark, inspect_profile, serve_offline
tests/            offline test-suite and recorded fixtures
```

## 14. Limitations

* NAV job postings, LinkedIn, Glassdoor etc. are deliberately not collected (no permitted matching by
  organisation number / not permitted). Hiring comes from company-owned careers pages and linked ATS.
* Without `TAVILY_API_KEY`, companies whose register entry lists no website and whose e-mail uses a
  webmail domain get no website (reported as `not_available`, never guessed).
* Websites that render content only with JavaScript expose little HTML; the agent reports what it can
  verify and does not run a headless browser.
* The registry API gives role holders but not role start dates; "since" dates are therefore not shown.

See `RUNBOOK.md` for operating the live run and `docs/IMPLEMENTATION_REPORT.md` for what was verified.
