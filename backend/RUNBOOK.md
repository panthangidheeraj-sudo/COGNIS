# RUNBOOK — running COGNIS for real

Step-by-step for a Windows machine (PowerShell). macOS/Linux differences are in brackets.

## A. First-time setup (10 minutes)

1. Open PowerShell in the project folder, then go into the backend:
   ```powershell
   cd "C:\Users\User\OneDrive\Desktop\COGNIS\backend"
   ```
2. Create and activate a virtual environment, install pinned dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1                      # [source .venv/bin/activate]
   python -m pip install -r requirements-dev.txt
   ```
   (After updating COGNIS, run this line again: the PDF report needs `reportlab`, `pillow` and `charset-normalizer`.)
   You should see `(.venv)` at the start of the prompt from now on.
3. Create your config file and open it in an editor:
   ```powershell
   copy .env.example .env
   notepad .env
   ```
   * Because the project lives in OneDrive, set a local data folder (avoids SQLite file locking):
     `DATA_DIR=C:\Users\User\AppData\Local\cognis`
   * Optional LLM: `LLM_PROVIDER=groq`, `GROQ_API_KEY=<your key>`, `GROQ_MODEL=<a model your key may use>`.
     On a free plan also set `LLM_MIN_INTERVAL_SECONDS=2`.
   * Optional web discovery: `TAVILY_API_KEY=<your key>` (free plan: 1,000 searches/month; key starts with `tvly-`).
   * No paid keys are needed. NAV job ads and TED procurement are free and on by default; NAV uses its public
     token unless you set `NAV_FEED_TOKEN` (a free private token NAV issues by e-mail to
     nav.team.arbeidsplassen@nav.no — recommended for regular use). `PROFF_API_KEY` / `DOFFIN_API_KEY` lines can be
     deleted from `.env`; they are ignored.
   * Optional: build the NAV job-ad index once (`python scripts/sync_nav_feed.py --until-done`; the API server keeps it
     fresh afterwards) and import DFØ's open Doffin files (`python scripts/import_doffin_open_data.py <files>`).
4. Check everything works offline:
   ```powershell
   python -m pytest -q
   ```
   Expected: all tests pass (the suite includes `tests/test_report_export.py`, which builds real PDFs and reads them back; it takes about a minute).

## B. Live smoke test (the 100-company check)

```powershell
python scripts/smoke_test.py --live
```

* Takes roughly 4–12 minutes (Regnskapsregisteret's copy endpoint is spaced 2.1 s per request).
* Writes `out\smoke-live\smoke-report.md` and the envelopes / profiles / run reports next to it.
* What to look at in the report: validation **passed**, entity states, coverage per field, module states
  (many `blocked_robots` or `source_error` means a network problem), requests and cost under budget,
  and the re-run line (second run is mostly cache hits; on live data a few changes can be real).

Per-company budgets differ by research mode: Deep uses `PER_COMPANY_MAX_SECONDS` / `PER_COMPANY_MAX_REQUESTS` / `MAX_SEARCHES_PER_COMPANY` (30 requests, 120 s, 3 searches by default); Quick uses the smaller `QUICK_MAX_SECONDS` / `QUICK_MAX_REQUESTS` / `QUICK_MAX_SEARCHES` (60 s, 20 requests, 1 search) and is never allowed more than Deep. If Deep runs on large sites regularly show `blocked_by_budget` in the run's operations, raise the Deep values; the essential registers are not subject to these caps.

Then inspect a few companies by hand:

```powershell
python scripts/inspect_profile.py 923609016
python scripts/inspect_profile.py <an org number from the smoke list that has a website>
```

Check that every published website really belongs to that organisation number (the `WEBSITE CANDIDATE`
lines show the identity signals) and that revenue figures carry the right FY period.

## C. The evaluator command

```powershell
python scripts/run_competition_batch.py --organisations orgs.jsonl --bulk enheter.csv `
  --output out\envelopes.jsonl --profiles-output out\profiles.jsonl --report out\run-report.json `
  --run-id final-1 --expected-count 100
```

* Exit code 0 = all 100 envelopes written and valid; 1 = completeness validation failed (see report);
  2 = input/configuration error (message printed).
* Interrupted? Run the same command with `--resume` (same `--run-id`).
* Refresh / change detection: next time add `--previous-profiles out\profiles.jsonl` (use a new run id
  and new output names).

## D. Running the app

```powershell
# terminal 1
cd backend; .venv\Scripts\Activate.ps1; uvicorn app.api.main:app --port 8000
# terminal 2 (project root)
npm run dev:live
```

Open http://localhost:5173. The top bar shows **Connected** when the frontend talks to the backend.

## E. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `[config] ERROR: GROQ_API_KEY is set but GROQ_MODEL is empty` | add `GROQ_MODEL=llama-3.3-70b-versatile` (or another model your account may use) to `.env`, or remove the key |
| Data Sheets / Discover: “Company search in Enhetsregisteret failed” | The message now states the real cause (also in the backend log as `enhetsregisteret search failed`). `Could not connect … certificate` = a corporate proxy / antivirus HTTPS scanning / old certificate store; `could not be resolved` = DNS or VPN; `did not answer in time` or `HTTP 5xx` = the register is slow or down (retried 3 times automatically, then press Retry); `rejected the search request (HTTP 400)` = a filter value the register refuses (its own message is quoted); `not valid JSON` = a proxy or captive portal answered instead. `python scripts/live_check.py` (or `run_live_checks.cmd`) section 2 runs three real searches with the same parameters and prints the cause. When the register cannot be searched, Data Sheets offers to continue from companies COGNIS has already verified (your choice; the sheet is labelled) |
| Every website `blocked_robots` | robots.txt unreachable (network/proxy); check internet access |
| Many `source_error` on Brønnøysund | the register is down or rate-limiting; re-run with `--resume` later |
| `database is locked` | `DATA_DIR` is inside OneDrive — on Windows the backend now defaults to `%LOCALAPPDATA%\cognis` when the project is in OneDrive; otherwise set `DATA_DIR` (step A3) |
| `model_not_found` / `The model ... does not exist or you do not have access to it` | your Groq key cannot use that model. Run `scripts/live_check.py`: it lists the models your key can use. gpt-oss models need no extra setup (the backend sets a low reasoning effort). After one such refusal the backend stops calling the LLM for the rest of the run |
| LLM errors in envelopes (`llm:*`), `provider call failed (not_found 404)` | wrong model name or base URL. `python scripts/live_check.py` prints Groq's own error message, the models your key can use, and a ready-to-paste `GROQ_MODEL=` line. Rate limits (429): set `LLM_MIN_INTERVAL_SECONDS=2`. Research continues with deterministic fallbacks either way |
| Frontend shows mock data | you ran `npm run dev`; use `npm run dev:live` |
| Status shows NAV "Degraded" | the job-ad index is still being built or the feed could not be reached; run `python scripts/sync_nav_feed.py` and check the printed error. A 401 means NAV rotated its public token (it is re-fetched automatically) or your `NAV_FEED_TOKEN` expired |
| A profile says "NAV Arbeidsplassen could not be checked" or "Hiring source unavailable" | NAV (or a careers page / job board) timed out or refused access during that run. This is deliberately not shown as "no openings". Re-run the company later; every request has a wall-clock deadline (`HTTP_TOTAL_TIMEOUT_SECONDS` 30, `DNS_TIMEOUT_SECONDS` 5; NAV: `NAV_REQUEST_TIMEOUT_SECONDS` 8 with `NAV_RETRY_ATTEMPTS` 1), `NAV_STEP_TIMEOUT_SECONDS` (default 20) and `NAV_MAX_CONSECUTIVE_FAILURES` (default 2) bound how long NAV can hold up a company, and once NAV has proved unreachable it is not asked again for `NAV_UNAVAILABLE_COOLDOWN_SECONDS` (default 90) — later companies report the same reason at once. The company's own careers pages are capped by `JOBS_STEP_TIMEOUT_SECONDS` (60) and the optional job-page search by `JOBS_DISCOVERY_TIMEOUT_SECONDS` (30). The Source Activity step for hiring is then **failed** (not completed) |
| Job pages found by search are never used | `ENABLE_JOB_DISCOVERY=false`, no `TAVILY_API_KEY`, or the company's own careers pages already show a current opening (search is then skipped). Candidates and the reason each was rejected are in the record under `jobs.discovery_candidates` |
| Recent activity shows only register entries, or says "No company announcements could be read" | The section lists exactly what was checked (newsroom, investor relations, feeds, press search, registers) and what each returned. `blocked` = robots.txt or the site refused access (never worked around); `no dated items` = the page loads its news by script, which COGNIS does not run; `not checked` = no verified website, no `TAVILY_API_KEY`, or the plan left company news out. None of these means the company announced nothing. The same detail is in the saved record under `news.newsroom.sources` and `news.search.candidates` |
| Press articles are not appearing in Recent activity | They need `TAVILY_API_KEY`, `ENABLE_SECONDARY_NEWS=true` (default) and deep research. Only outlets in `SECONDARY_NEWS_DOMAINS` are fetched, each article must show a date and name this exact organisation (organisation number, or the exact registered name in the headline — "Autobjørn Bergen AS" is not "Autobjørn AS"), and robots.txt is respected. The reason each candidate was rejected is in `news.search.candidates` |
| Import says "no organisation-number column with a known role" | the Doffin file names its columns differently; run with `--dry-run` to see the headers and map them, e.g. `--map winner_org="Leverandør org.nr"` |
| Export → Full Research Report says “PDF reports cannot be produced on this installation” / “PDF reports are turned off”, or the option is greyed out | the report needs `reportlab` (with `pillow` and `charset-normalizer`) and the bundled fonts in `app/assets/fonts/` (Liberation Sans/Serif, SIL OFL, licence included). The startup log and the status popover name what is missing. Run `python -m pip install -r requirements.txt` in `backend` with the virtual environment active, restart the backend, and make sure the fonts folder was copied with the project. A missing ReportLab no longer takes `/status` down (it used to fail with `ModuleNotFoundError: No module named 'reportlab'` and the app showed “Backend offline”) |
| The status capsule says “Status check failed” | the backend answers `/health` but `/status` returned an error. Research may still work; the backend console shows the cause |
| Discover cards say “Not checked”, “Not reported” or “None verified” | these are honest states, not missing data: the lookup was not possible (no register-listed website, NAV index not synced yet), the official source holds no value (no filed accounts, no registered employee count), or the job sources were checked and showed no verified opening. Open the company and run Quick research for a full check |
| Export says “No saved research exists for this company yet” | the report and the evidence export read the saved research and never start new research. Open the company and run research first, then export |
| `UnicodeEncodeError` in the console | use Windows Terminal / PowerShell 7, or `set PYTHONUTF8=1` |

## F. Operational guarantees

* One terminal envelope per input — also under timeouts, budget exhaustion and source failures.
* A failed or blocked source is reported as such, never as "no data".
* Keys never appear in logs, records, envelopes or the database (tested in `tests/test_security.py`).

## G. Ask AI chat and regulatory sources (free allowances only)
- Endpoints: `GET /companies/{org}/chat/context`, `POST /companies/{org}/chat`, `GET /companies/{org}/regulatory`.
- Existing variables: `TAVILY_API_KEY` (free plan, no card), `GROQ_API_KEY`, `GROQ_MODEL`, `LLM_PROVIDER`. New: `ENABLE_REGULATORY_DISCOVERY`, `REGULATORY_MAX_PAGES`, `REGULATORY_DOMAINS`, `ENABLE_CHAT`, `CHAT_MAX_QUESTION_CHARS`, `CHAT_MAX_HISTORY_MESSAGES`, `CHAT_MAX_SEARCHES`, `CHAT_FRESH_TIMEOUT_SECONDS`, `CHAT_LOOKUP_TIMEOUT_SECONDS`, `CHAT_LOOKUP_PAGE_TIMEOUT_SECONDS`, `CHAT_LOOKUP_MAX_PAGES`, `CHAT_LOOKUP_CACHE_SECONDS`, `CHAT_FRESH_MAX_AGE_HOURS`, `CHAT_MAX_EVIDENCE_ITEMS` (see `.env.example`).
- Without a Groq key the chat still answers, from saved evidence only, and says so. Without a Tavily key (or when its free allowance is used up) fresh research is reported as unavailable; nothing paid is started.
- Source rules and limits: `docs/SOURCE_ACCESS_AUDIT.md`.
