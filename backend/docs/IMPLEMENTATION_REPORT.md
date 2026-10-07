# Implementation report — COGNIS backend

## What was built

* **Research engine** (`app/agent/orchestrator.py`): identity from Enhetsregisteret (live, bulk fallback)
  → official modules in parallel (roles, establishments, group, accounts, filed-report years) → website
  discovery (register field, registered e-mail domain, establishment sites, optional Tavily search) with
  a deterministic identity gate (Norid holder check for .no domains) → enrichment of verified sites only
  (careers + linked ATS job boards, news, contact, social links) → bounded LLM research loop (the model
  picks from page fetches Python offers) → quote-verified LLM extraction → publication gate → explicit
  absences → evidence-grounded summary (LLM with number check, template fallback). Always terminal.
* **Evaluator contract** (`app/competition/`): OUTPUT_CONTRACT envelopes, starter-compatible batch CLI
  (`scripts/run_competition_batch.py`, same arguments), one-command `scripts/run_agent.py`, refresh replay
  (`scripts/run_refresh_replay.py`), change detection on starter-compatible profiles, completeness
  validator, resumable runs, budget-exhaustion fallback that still emits terminal envelopes.
* **Product API** (`app/api/`): every endpoint in `API_CONTRACT.md`, with the mock's response shapes:
  status, search, discover/interpret (Brønnøysund search with municipality/industry/size/founded filters),
  company profile (registry lookup first, full research on demand), brief, explain, ask, research runs
  with SSE replay by `lastSeq`, library + versions + version compare + reports + assessment, data sheets
  with AI-column preview and SSE batch research, compare, watchlist + signal feed, CSV/JSON/XLSX exports.
* **Storage** (SQLite, WAL): companies, source snapshots, evidence, facts + fact versions, changes,
  profile versions (content-hashed, idempotent), research/company runs, tool calls, response cache,
  artifacts, sheets, watchlist, signals, exports.
* **Safety**: SSRF policy re-checked per redirect hop and after DNS, size/time limits, robots.txt,
  per-host concurrency, central budgets, retry policy, secret redaction, no secrets in records.

## Verification done here (offline — the sandbox cannot reach brreg.no or Groq)

| Check | Result |
| --- | --- |
| `pytest` | 106 passed (security, HTTP policy, identity, gate, LLM validation, 15 evaluation scenarios, envelope contract, batch + budget exhaustion, refresh replay, API contract incl. SSE) |
| `ruff check app scripts tests` | clean |
| Refresh replay on the starter fixture | 2/2 expected changes, 0 false positives, evidence complete, idempotent → qualification passed |
| 100-company offline smoke test (real universe rows, synthetic responses, injected failures) | 100/100 terminal envelopes, validation passed, 0 wrong-company or unverified websites published, re-run 0 changes |
| Offline benchmark (100 companies) | ≈ 8 requests per company, $0 third-party cost, all within budgets |
| Frontend in live mode against the API (`npm run dev:live` + offline server), 11 pages + full research run | 0 console errors, 0 failed API calls; profile, research stream, completion summary, library, compare, sheets, watchlist render from backend data |

## Financial currency (QA fix, Equinor ASA 923609016)

The register filed Equinor's accounts in USD, but exports showed `value = "NOK 67.96B"` beside an evidence excerpt that said `… 67960000000 USD …`. The parser and evidence were correct; the display layer (`format_nok`) and ~30 hard-coded `"NOK"` units/labels (profile series/section/snapshot, briefs, ask/summary text, compare, sheets, exports, Discover, and the frontend formatters/cards/charts) overrode the record's currency. Now each filing's `valuta` is carried through unchanged and used for every label; nothing is converted; a missing `valuta` is shown as "currency not stated". `tests/test_currency.py` (backend, 16 tests incl. a source-scan guard against hard-coded NOK) and `src/tests/currency*.test.ts(x)` (frontend) cover Equinor-style USD, a NOK→USD switch, a filing with no currency, mixed-currency compare and the NOK revenue filter. The gate got stricter, not looser (currency must appear in its own evidence span).

## What still needs your machine

The live 100-company smoke test and benchmark (`RUNBOOK.md`, section B) — they need internet access to
data.brreg.no and company websites. Expected live cost per company: 7–12 HTTP requests (+1–4 LLM calls
when Groq is configured); the batch defaults stay inside 2000 requests / $10 / 45 minutes for 100 companies.

## Known limitations

See README §14. Also: pypdf is installed but filed PDF reports are only listed (not parsed) because
Regnskapsregisteret's JSON API already provides the structured figures with periods.
