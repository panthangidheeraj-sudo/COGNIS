# COGNIS — Builderr Signalpost submission

**Company intelligence, built from evidence.** A React/TypeScript workspace plus a Python/FastAPI backend that finds, verifies and compares Norwegian companies. Every published fact carries its source, retrieval time and period. Missing, blocked, ambiguous and conflicting data each have their own label; a failed source is never shown as "no data".

**How to read the numbers.** *Measured* = taken from a report or log produced by a real run (file named). *Estimate* = computed, not observed. *PENDING* = not yet verified. **Three kinds of results are kept apart.** (1) *Historical live runs* of 2026-10-15 (live check, 100-company smoke test, cached re-run): real public sources, made on the author's PC, and they **predate the latest code**. (2) *Local offline test and build results* of 2026-10-17: mocked/fixture tests, not live evaluation. (3) *A 1,000-company exercise* run as ten separate batches of 100 against the bundled fixture (own section below): author-reported aggregates, not one run under the challenge limits. Nothing here is a provider invoice. See "Remaining limitations" for what is not verified.

## Repository and commit

| Item | Value |
| --- | --- |
| Repository | https://github.com/panthangidheeraj-sudo/COGNIS (`origin` in `.git/config`). **The repository is public** (author's statement, 2026-10-17) |
| Version 1 submission commit | `4ea5b3650d51fff0b428230e18a9d0f775aae711` — https://github.com/panthangidheeraj-sudo/COGNIS/commit/4ea5b3650d51fff0b428230e18a9d0f775aae711 |
| This document | A **later revision** of `SUBMISSION.md` (documentation correction only; no application code, tests, configuration or benchmark output changed). Its commit hash is **not stated here**; it will be supplied separately after the revision is pushed |

The Version 1 commit above is the submitted version. Evaluators who want the submitted code should check it out as shown below; the later revision changes this document only.

## Evaluator run (one command)

Prerequisites: **Python 3.11+ and internet access.** Node is not needed for this path. The evaluator supplies its own organisation numbers; no fixed internal company list is used.

From a clean clone:

```bash
git clone https://github.com/panthangidheeraj-sudo/COGNIS.git
cd COGNIS
git checkout 4ea5b3650d51fff0b428230e18a9d0f775aae711
cd backend
python -m venv .venv
```

Activate `.venv` for your operating system:

```bash
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\Activate.ps1         # Windows PowerShell
.venv\Scripts\activate.bat         # Windows cmd
```

Install the pinned runtime dependencies (`backend/requirements.txt`):

```bash
python -m pip install -r requirements.txt
```

Put the evaluator-supplied organisation numbers in `backend/orgs.txt`, **one number per line** (`.json` and `.jsonl` lists are also accepted). Then run, from `backend` with the environment activated:

```bash
python scripts/run_agent.py --input orgs.txt --output out/envelopes.jsonl
```

`scripts/run_agent.py` is the primary evaluator interface. The `--input` and `--output` paths can be changed. The run writes:

- `out/envelopes.jsonl` — one terminal envelope per organisation number;
- `out/envelopes-profiles.jsonl` — profiles (default location next to `--output`; override with `--profiles-output`);
- `out/envelopes-report.json` — the run report, including validation (default next to `--output`; override with `--report`).

It prints a short JSON summary and exits 0 when validation passed, 1 when it did not, and 2 on an input error. Optional flags: `--bulk <Brreg snapshot>`, `--workers`, `--run-id`, `--resume`, `--fresh` (bypass the response cache), `--quiet`. `scripts/run_competition_batch.py` (more budget options, `--expected-count`) remains available for advanced use but is not needed.

No API keys are required: without them the system uses the official registers and registry-listed websites, and falls back to deterministic text where a model would be used. To use Groq and Tavily, the evaluator supplies **its own** credentials through its local environment or an untracked `backend/.env` (see "AI model and provider"). No personal API keys are in the repository.

**Not yet verified:** these exact commands have not been followed on a fresh clone (see "Remaining limitations").

Limits enforced by the run budget (`backend/app/config.py`): 2,700 s, 2,000 requests, $10, headroom 0.9, 8 parallel companies. Per company (Deep): 30 requests, 120 s, 3 searches, 4 LLM calls.

## Developer quick start (UI and API)

Prerequisites: Node 20+, Python 3.11+ (3.13 tested), Windows PowerShell (macOS/Linux notes in `backend/RUNBOOK.md`).

Frontend with the built-in mock backend (fictional demo data): `npm install && npm run dev` → http://localhost:5173

Real backend with the UI (two terminals):

```powershell
# terminal 1
cd backend; python -m venv .venv; .venv\Scripts\Activate.ps1; python -m pip install -r requirements-dev.txt
copy .env.example .env      # keys are optional, see below
uvicorn app.api.main:app --port 8000
# terminal 2 (project root)
npm run dev:live
```

Backend `.env` (git-ignored; never commit): `LLM_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL` (required when a key is set, e.g. `openai/gpt-oss-120b`), `TAVILY_API_KEY`, `DATA_DIR` (a local folder if the project is in OneDrive), optional `NAV_FEED_TOKEN`, `LLM_MIN_INTERVAL_SECONDS` (see the Groq finding below). Without keys the system runs on the official registers and registry-listed websites. Never put keys in `VITE_*` variables.

## AI model and provider

- LLM: Groq `openai/gpt-oss-120b` (as configured in the 2026-10-15 live check). Planning, reading verified pages, summaries and Ask AI. A model answer is shown only if each claim is supported by saved evidence; otherwise a deterministic, evidence-only text is used and labelled (`synthesis.method`).
- Search: Tavily Basic Search, used only to discover candidate websites, never as evidence. Everything else is free public data.
- **Credentials:** no personal API keys belong in the repository, and none are committed. The evaluator can supply its own Groq and Tavily credentials through its local environment or an untracked `backend/.env`; without them the run still completes on free public data with deterministic summaries.
- **Groq free tier throttled the run (measured 2026-10-15, `smoke-1-envelopes.jsonl`; predates the latest code).** Groq answered 429 "tokens per minute: limit 8000" on 56 final LLM failures (47 summaries, 9 website extractions) spread over 47 of the 100 companies. The rejected calls asked for 691–2,380 tokens each (median 1,374), so the free tier sustains roughly 5–6 such calls a minute (arithmetic from those figures, an estimate). Summaries: 37 LLM-grounded, 63 deterministic template (47 rate-limited, 16 rejected by the grounding check). Only 57 LLM calls succeeded out of 193 attempts. The live check ran with `LLM_MIN_INTERVAL_SECONDS=0` and 8 parallel companies. The behaviour is safe (fallback, labelled) but the summaries in that run were mostly not AI-written. **PENDING:** a run with pacing. By the arithmetic above, call starts need to be at least about 11 s apart (`LLM_MIN_INTERVAL_SECONDS=11`), not 2–7 s; untested.

## Cost and request accounting

- **Requests (measured):** the counter reserves one request per HTTP attempt, including retries and redirects, and refunds cache hits (`backend/app/net/http.py`). It includes robots.txt, Tavily and LLM calls. It does not count DNS lookups.
- **LLM cost (estimate):** recorded per call as `chars/4 × $0.0005/1k + max_tokens × $0.0008/1k`, and refunded when the call fails. The prices are configurable placeholders. Groq's published price for this model is $0.15 input / $0.60 output per 1M tokens ([Groq model page](https://console.groq.com/docs/model/openai/gpt-oss-120b)), lower than the placeholders, and the output side uses `max_tokens`, not actual output. The reported $0.0607 is therefore probably an over-estimate. Actual token usage and the Groq invoice were **not** recorded or verified; the free tier would bill $0.
- **Tavily (measured count, documented credit price):** the first 100-company run made 110 searches; the cached re-run made none. Tavily charges 1 credit per basic search and the free plan has 1,000 credits a month ([Tavily docs](https://docs.tavily.com/documentation/api-credits)), so about nine uncached 100-company runs per free key per month (arithmetic, not measured). If the evaluator uses your key, that is a limit to plan around.

## Verified results

### Local offline test and build results (2026-10-17)

Run on the author's Windows PC and reported by the author for **2026-10-17** (mocked/fixture tests, no live sources). The commit hash of the working tree they ran on is not recorded in this report:

| Check | Result |
| --- | --- |
| Backend tests (`python -m pytest -q`) | **592 passed, 0 failed, exit code 0** |
| Frontend tests (`npm test`) | **479 passed across 38 test files** |
| Production build (`npm run build`) | **succeeded in 4.52 seconds** |

These are **local offline test and build results, not live evaluation results**. They show the code behaves as specified against fixtures; they say nothing about live source coverage, speed or cost (see the live sections below and "Remaining limitations").

### Live check, 3 companies (2026-10-15, `backend/out/live-check.md`, measured; predates the latest code)

Brønnøysund, Groq (structured JSON in 632 ms), Tavily, NAV and TED reachable. Equinor ASA (923609016), Autobjørn A/S (810359862) and Arkitektfirma Jon Vikøren AS (985589003) all completed with valid envelopes and websites verified by identity signals. 22–30 requests and 2–3 LLM calls each. The API (company, research run, brief, `/research/ask`, interpret, discover) returned real data. Revenue was labelled company-only and in the filing currency (Equinor: USD).

### 100-company live smoke test (15 October 2026, `backend/out/smoke-live/`, measured) — historical benchmark

**This is a single 100-company run measured on 2026-10-15. It predates the latest code, has not been re-measured on it, and is not merged with the ten-batch totals below.** Recorded: 100 envelopes, 1,569 requests, 288.9 s, $0.0607 cost estimate. `python scripts/smoke_test.py --live`: 100 organisations sampled with `random.Random(2026)` from the 1,000-row `backend/tests/fixtures/entry-companies.jsonl`.

| Target | Limit | Measured |
| --- | --- | --- |
| Companies | 100 | 100 terminal envelopes; validation passed (exact count, unique, no silent drops, evidence integrity) |
| Duration | 45 min | 288.9 s |
| Outbound requests | 2,000 | 1,569 (306 Brønnøysund, 371 website, 234 robots, 193 LLM, 110 Tavily, 100 TED, 48 Norid, rest other) |
| External cost | $10 | $0.0607 (estimate, see above) |

Per company: median 15 requests, p90 23, maximum 29. No company reached the 30-request cap and none hit a budget limit. Per-company runtime p50 16.8 s, p95 40.4 s. Coverage (companies with an available value): legal name, status and industry 100; board chair 96; revenue 84; CEO 66; registered employees 17; official website 12; business description 10; open positions 0. Websites: 12 verified, 17 ambiguous (not published), 28 candidates rejected for showing another organisation number. Hiring "none found" never means a company is not hiring.

### Re-run stall (2026-10-15 cached re-run; investigated; cause unproven)

The cached re-run took 426 s and reported a per-company p95 of 283 s, above the 120 s limit. From the envelope files: exactly 8 companies (the number of parallel workers) took 264–302 s with 0–4 requests and 0 LLM calls each, started together, and finished together at 04:22:48–51 UTC. The other 92 took at most 42 s. One of the 8 recorded "per-company time limit reached", but the others finished normally after far longer than the 135 s timer, which means the timers did not fire: the whole process or event loop was stalled for about five minutes, not the sources. In the first run no company exceeded 120 s.

Not reproduced offline (two runs of 100 companies against the offline fixtures with a file database: maximum loop lag under 0.1 s). I could not read the request log (`smoke-live.sqlite`, 272 MB) to see what the process was doing, so a code cause is **not proven** and an environmental pause (sleep, antivirus, console freeze) is not ruled out. No behaviour was changed. To make the next occurrence diagnosable, the batch runner now measures event-loop lag and writes `event_loop_lag` (max lag, stalls over 5 s) into the run report and `smoke-report.md` (`backend/app/runtime/lag.py`, wired in `batch.py`, tests in `backend/tests/test_loop_lag.py`). The first-run result that the evaluation resembles is unaffected.

### 1,000-company input list (verified)

`backend/tests/fixtures/entry-companies.jsonl`: 1,000 rows, 1,000 unique 9-digit organisation numbers, all pass the modulus-11 check, none bankrupt or in liquidation, all with 2025 accounts submitted. Mix: 926 AS, 204 in Oslo, 893 without a registered website. **Not verified:** that the list was selected from the official 411,160-company universe (that file is not in the repository). The ten-batch exercise below ran on this list; it is not a single run, and it does not show that the list represents the full universe.

### 1,000-company exercise: ten separate batches of 100 (author-reported aggregates)

The bundled 1,000-row fixture was processed as **ten separately executed batches of 100 companies**, not as one run. The fixture is a bundled list, **not a random sample of the full official company universe** (see above), so the results do not show how the full universe would behave. The figures below are the aggregates reported by the author; per-batch figures are not tabulated here.

| Aggregate over the ten batches | Reported |
| --- | --- |
| Input organisation numbers | 1,000, all unique |
| Output envelopes / profiles | 1,000 / 1,000 |
| Structural validation | Passed in every batch |
| Companies with at least one available claim | All 1,000 |
| Envelopes with one or more error entries | 808 of 1,000 |
| Summaries | 201 grounded LLM synthesis; 799 deterministic template |
| Requests (sum of the ten batches) | 13,462 |
| Runtime (sum of the ten batch runtimes) | 3,000.67 s (about 50.01 minutes) |
| Cost (sum of the program's cost estimates) | $0.324243 — an **estimate**, not a provider invoice |

How to read this:

- **These are ten separate runs.** The sums are **not** one run under the challenge's 2,000-request / 45-minute limits: 13,462 requests and 3,000.67 s exceed those limits when added up, because they are ten runs added together. This document does not claim a single 1,000-company run met them, and does not claim each batch individually did.
- "At least one available claim" is the weakest coverage test. It does not mean a profile is fully researched; 808 envelopes carry error entries (failed, blocked or timed-out source calls or rejected steps), and the field-level coverage of these batches is not reported here. Compare the field-level coverage of the 100-company run above.
- Only 201 of 1,000 summaries are AI-written. The 799 deterministic summaries are labelled as such; the split reflects provider limits and grounding rejections, not a quality ranking.
- **Provider limitations met in these runs:** Groq hit its rate limits, including its **daily token limit during the later batches**; **Tavily exhausted its free search credits**, so candidate website discovery was limited accordingly; some summaries were rejected by the grounding check; and some sources failed or timed out. Failures degrade to labelled deterministic or "unavailable" results, never to invented values.
- The cost figure uses the program's configurable price placeholders (see "Cost and request accounting"); actual token usage and provider invoices were not recorded or verified.

## Requirement status

Single-run measurements are from the 2026-10-15 100-company run (historical, predates the latest code). The ten-batch figures are sums of separate runs and are shown separately.

| Target | Status |
| --- | --- |
| 1,000 company profiles | List verified. Ten separate batches of 100 produced 1,000 envelopes and 1,000 profiles (author-reported; see the ten-batch section). **Not** one 1,000-company run, and not evidence about the full universe |
| Daily 100 random companies | One seed (2026, from the 1,000-row list) run live on 2026-10-15. Independent random-seed coverage (other seeds, the full universe) **PENDING**. The 1,000 list is mostly small AS companies; coverage elsewhere may differ |
| Within 45 minutes | Measured 288.9 s for one 100-company run (2026-10-15). The ten-batch sum of 3,000.67 s is ten runs added together, not one run |
| At most 2,000 requests | Measured 1,569 for one 100-company run; hard cap enforced by the run budget. The ten-batch sum of 13,462 is ten runs added together |
| At most $10 | Estimates only: $0.0607 (one 100-company run), $0.324243 (sum over the ten batches). Provider invoice not verified |

## Data sources and limits

Table and access rules: `backend/docs/SOURCES.md`, `backend/sources.yaml`, `backend/docs/SOURCE_ACCESS_AUDIT.md`.

Used (free/public): Enhetsregisteret (units, roles, group structure), Regnskapsregisteret (company and consolidated accounts), Norid RDAP, Geonorge, company websites and linked job boards (robots.txt respected), NAV Arbeidsplassen job-ad feed, TED (EU above-threshold notices only), DFØ Doffin open data (importable; not imported in the live checks), Tavily Basic Search (candidate discovery only; free credits can run out, see the ten-batch section). The full table and access rules are in `backend/sources.yaml` and `backend/docs/SOURCE_ACCESS_AUDIT.md`.

Not used or unavailable: Proff, paid Doffin API, Fakt.no, LinkedIn, Meta, Glassdoor, Indeed. Patentstyret is `not_configured`; the shareholder register is `not_applicable`. Patents, trademarks and designs are never reported as "none" when the source is unavailable.

## Large companies

(2026-10-15 live check.) Equinor reached the 30-request cap in the live check, so its LLM summary failed with `budget_exhausted`, TED was reported `blocked · budget_exhausted`, and a deterministic summary was used, all labelled in the envelope. In the 100-company run no company reached the cap, so the effect on a random sample is **not measured**; it grows with company size.

## Live validation of Ask AI

The AI-chat work (`/companies/{org}/chat`, chat threads, company switching, regulatory sources, source-consistency labelling, and the separation of total liabilities from debt) was added after the 2026-10-15 live checks. It is covered by the offline tests above (identity and company switching, company-only vs consolidated, period and currency, citations, direct filing link vs register data record, event status, unavailable sources, no credentials in threads, and metric definitions: the register's "sum gjeld" is shown as total liabilities, never as debt).

**Manual smoke check (author, on or before 2026-10-17):** one manual live Ask AI test returned an answer with dated sources. This is a **manual smoke check only, not comprehensive live validation**: no systematic set of companies or questions was run, and no accuracy, latency, cost or rate-limit figures were recorded for it. Comprehensive live validation of Ask AI is **PENDING**.

## Reproduce

```powershell
cd backend
python scripts/run_agent.py --input orgs.txt --output out/envelopes.jsonl   # evaluator run (see "Evaluator run")
python -m pytest -q                                              # offline tests
python scripts/live_check.py                                     # real sources, writes out/live-check.md
python scripts/smoke_test.py --live                              # 100 companies (seed 2026), writes out/smoke-live/smoke-report.md
python scripts/smoke_test.py --live --seed 7 --fresh --out out\smoke-seed7   # another random 100, cache bypassed
python scripts/benchmark.py --live --count 20                    # runtime / requests / cost per company
```

`backend\run_live_checks.cmd` runs tests, live check and smoke test in one go (reports in `backend\out\`, git-ignored). Frontend: `npm install && npm test && npm run build`.

## Remaining limitations

- Website coverage is low by design (12/100 verified): wrong-company sites are rejected, not published. Descriptions (10/100) and open positions (0/100) follow from that.
- NAV covers only ads registered with NAV; TED does not cover below-threshold procurement.
- Company-only and consolidated accounts are never mixed.
- With the Groq free tier, summaries mostly fall back to deterministic text unless calls are paced.

Outstanding (not verified or not done; none of these is claimed):

- **Clean-clone installation not verified**: the "Evaluator run" commands have not been followed on a fresh clone of the public repository at the Version 1 commit.
- **No verified Groq invoice**: all cost figures are estimates; actual token usage was not recorded.
- **Paced-run verification pending**: a run with `LLM_MIN_INTERVAL_SECONDS` set (about 11 s by the arithmetic above) has not been made.
- **Independent random-seed coverage pending**: only seed 2026 has been run live as a single 100-company run; the ten batches covered the bundled fixture and are not presented as independent random samples.
- **Full-universe representation not shown**: the bundled 1,000-row fixture is not shown to represent the official company universe. There is no single 1,000-company run under the 2,000-request / 45-minute limits; the exercise was ten separate batches.
- **Ten-batch results are author-reported aggregates**: the batches were rate-limited by Groq (including its daily token limit) and Tavily (free credits exhausted), so most summaries are deterministic and many envelopes carry error entries.
- **Comprehensive live Ask AI validation pending**: there has been one manual smoke check only.
- The 100-company benchmark figures (2026-10-15) predate the latest code and have not been re-measured.
