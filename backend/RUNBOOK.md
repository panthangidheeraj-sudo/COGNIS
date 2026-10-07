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
4. Check everything works offline:
   ```powershell
   python -m pytest -q
   ```
   Expected: `75 passed`.

## B. Live smoke test (the 100-company check)

```powershell
python scripts/smoke_test.py --live
```

* Takes roughly 4–12 minutes (Regnskapsregisteret's copy endpoint is spaced 2.1 s per request).
* Writes `out\smoke-live\smoke-report.md` and the envelopes / profiles / run reports next to it.
* What to look at in the report: validation **passed**, entity states, coverage per field, module states
  (many `blocked_robots` or `source_error` means a network problem), requests and cost under budget,
  and the re-run line (second run is mostly cache hits; on live data a few changes can be real).

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
| Every website `blocked_robots` | robots.txt unreachable (network/proxy); check internet access |
| Many `source_error` on Brønnøysund | the register is down or rate-limiting; re-run with `--resume` later |
| `database is locked` | `DATA_DIR` is inside OneDrive — on Windows the backend now defaults to `%LOCALAPPDATA%\cognis` when the project is in OneDrive; otherwise set `DATA_DIR` (step A3) |
| `model_not_found` / `The model ... does not exist or you do not have access to it` | your Groq key cannot use that model. Run `scripts/live_check.py`: it lists the models your key can use. gpt-oss models need no extra setup (the backend sets a low reasoning effort). After one such refusal the backend stops calling the LLM for the rest of the run |
| LLM errors in envelopes (`llm:*`), `provider call failed (not_found 404)` | wrong model name or base URL. `python scripts/live_check.py` prints Groq's own error message, the models your key can use, and a ready-to-paste `GROQ_MODEL=` line. Rate limits (429): set `LLM_MIN_INTERVAL_SECONDS=2`. Research continues with deterministic fallbacks either way |
| Frontend shows mock data | you ran `npm run dev`; use `npm run dev:live` |
| `UnicodeEncodeError` in the console | use Windows Terminal / PowerShell 7, or `set PYTHONUTF8=1` |

## F. Operational guarantees

* One terminal envelope per input — also under timeouts, budget exhaustion and source failures.
* A failed or blocked source is reported as such, never as "no data".
* Keys never appear in logs, records, envelopes or the database (tested in `tests/test_security.py`).
