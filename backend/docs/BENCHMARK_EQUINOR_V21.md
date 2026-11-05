# Equinor benchmark — before / after the V2.1 improvements

Organisation 923609016 (Equinor ASA), keyless mode (no LLM, no search API). Written 2026-11-05.

## 1. Status: what was and was not done

| Step requested | Status |
|---|---|
| 1. Run the updated backend against live sources | **NOT DONE.** The cloud sandbox's egress proxy answers 403 for data.brreg.no and equinor.com, and the app's HTTP client cannot resolve them. The PC link offers file transfer only (no shell, terminals are click-only), so nothing could be started there. I did not work around either limit. |
| 2. Compare with the previous benchmark | **Partly.** The previous (before) run is real, live data. The "after" column is offline evidence only until the live run in section 7 is done. `scripts/compare_benchmark.py` produces the full table from the two report files. |
| 3. Investigate the 26.6 s stall with the new diagnostics | **NOT POSSIBLE without a live run.** The diagnostics exist and are tested (section 4) but have captured nothing on a real run. Root cause is **unresolved**. |
| 4. Evaluate allocation, prioritisation, news quality, social | **Offline only** (synthetic fixtures and Equinor-shaped candidates). Live behaviour is unverified. |
| 5. Record failures / regressions / performance | Section 6. |
| 6. Update docs/SOURCES.md | Done (new section "Version 2.1 improvements"). |
| Run the tests again | Done: **719 passed** (cloud, full backend suite, 117 s). |

Nothing was committed or pushed. `.env` and `SUBMISSION.md` were not touched.

## 2. Baseline (BEFORE) — verified from the previous live run

Source: `out/v21-keyless/envelopes-report.json`, run `batch-9cefabb8b075`, 13:54:01Z–13:55:42Z.

| Metric | Value |
|---|---|
| Run elapsed | 100.71 s |
| Company runtime | 55.9 s |
| `operations.requests` (reported) | 68 |
| of which company-level (derived: 68 − 38 `nav_feed`) | 30 (= `per_company_max_requests`) |
| of which shared NAV index | 38 (`nav_feed`) |
| `requests_per_company` (reported) | 68.0 (mixed company and shared requests) |
| Requests by connector | nav_feed 38, website 20, brreg 5, robots 2, brreg_accounts 1, brreg_account_copies 1, company_ats 1 |
| NAV sync | 38 pages, 42.8 s, 26 000 upserts, 10 054 purged (first full sync) |
| Event-loop lag | max 26 594 ms, 1 stall (ended 13:55:34Z), threshold 5.0 s; no kind, no stack |
| Claims available | 244 |
| News | 5 published; 60 rejected/unusable, of which 8 future-dated listing items and the rest "not read: research budget for optional pages…"; 8 articles fetched |
| Social | 3 accepted (facebook, instagram, linkedin), basis `name_in_handle`, flat confidence 0.88 against a website score of 0.65 |
| Errors / validation | 0 / passed |

## 3. Verified findings (code reading plus tests, not a live run)

1. **The "68 requests against a limit of 30" was a reporting artefact, not a cap breach.** 38 of the 68 were the shared NAV index synchronisation; the company itself used exactly 30. Verified from the old report's per-connector counts. The new report splits the totals (`company_requests`, `shared_index_requests`, `requests_per_company` = company only). Regression tests: `tests/test_request_reporting.py` (4).
2. **The news cap exhausted the company's request allowance.** In the old run all 30 company requests were spent and the remaining candidates were labelled "research budget for optional pages". Verified from the old report; the wording was wrong (it was the company's request limit).
3. **Social confidence was flat and over-stated.** 0.88 for every accepted profile, higher than the website's own identity score (0.65), and the claim did not say that the profile page was never read. New code caps confidence by declaration type and website score and states "linked from the company website, not verified on the platform". Tests: `tests/test_social_verification.py` (+13).

## 4. Offline evidence for the AFTER behaviour

These come from the test suite and synthetic fixtures (`FixtureNetwork`), not from live Equinor pages.

| Area | Evidence |
|---|---|
| Request allocation | Synthetic site with 8 article cards, company cap 12: **1 article fetched without the reserve, 3 with it** (reserve 10). Caps 14 and 16: 3 and 5 fetched. Not-read candidates say "company's request limit (N requests)". |
| News ordering | On Equinor-shaped candidates, dated `/news/YYYYMMDD-…` articles rank above event, conference and generic listing pages. 26 tests in `tests/test_news_prioritisation.py`; key tests were mutation-checked (removing the merge or the ordering makes them fail). |
| Duplicates | Same address (scheme, www, trailing slash, tracking parameters ignored) or same headline plus date is merged before fetching; the count is reported. |
| True totals | `news_rejected_total` counts every rejection; at most 60 examples are stored; the report shows both. |
| Social | Ranking sameAs > footer > header > body; fragment handles ("equinorfans") rejected; confidence scales with the website score; body-only profiles demoted when the site declares one for that network elsewhere. |
| Stall diagnostics | `tests/test_loop_lag.py` (+6): a deliberate blocking call produces `kind = cpu_bound` or `blocked_or_suspended`, `cpu_share`, and a stack whose `top_frame` names the blocking function; a suspended process produces the "no stack" note. |

## 5. The 26.6 s stall — what is and is not known

**Verified:** one stall of 26.6 s, ending 13:55:34Z, 8 s before the run ended. NAV sync took 42.8 s and company work 55.9 s, so the two ran one after the other and 26.6 s is not simply the NAV sync. Reading the NAV lookup, sync and parser code did not reveal a 26 s synchronous section. The earlier V2 batches (100 companies) showed 3.9–5.0 s maximum lag.

**Unresolved:** the cause. Candidates, none confirmed: (a) the process was suspended (OneDrive sync of the project folder, antivirus scan, laptop power state); (b) a long synchronous SQLite commit or purge on the 300 MB database; (c) parsing a very large HTML page. The new diagnostic separates these directly: `kind = blocked_or_suspended` with an empty stack points to (a); `cpu_bound` with `top_frame` in the database layer points to (b); in `parse_html` to (c). No speculative change was made.

## 6. Failures, regressions, performance

* **Live run not executed** (section 1). Every "after" statement about live behaviour is unverified.
* **No regression found in the test suite:** 719 passed (V2.1 baseline plus 49 new tests). One existing assertion was deliberately changed (`threshold_seconds` 5.0 → 3.0).
* **Lint:** `ruff` reports 6 findings (import order and an unused loop variable in `agent/orchestrator.py`, an unused import in `extraction/web_facts.py`, a quoted annotation in `config.py`, unused imports in two test files). None affects behaviour; I could not check against the committed version because there is no git access from here, so I cannot say which were already present.
* **Comparability caveats for the live run:** the old run was a *first full* NAV sync (cold index, 42.8 s); a new run on the same database is incremental and will be faster, so NAV time must not be read as a speed-up of the code. Use `--fresh` for a cold page cache (the old run had 0 cache hits).
* **Known limitation unchanged:** social profile pages are never fetched, so no profile can be "platform verified"; `accepted_platform_verified` is always 0.
* **Behaviour change to watch:** the news reserve (default 10 requests) lowers the allowance for other optional work such as extra website pages. Check on the live run that website claim coverage did not drop below 244 claims.

## 7. Live run to complete the benchmark (on the PC)

From `C:\Users\User\OneDrive\Desktop\COGNIS\backend` in PowerShell:

```
$env:COGNIS_KEYLESS = "1"
python scripts/run_agent.py --input orgs.txt --output out/v21b-keyless/envelopes.jsonl --fresh
python scripts/compare_benchmark.py --before out/v21-keyless/envelopes-report.json --after out/v21b-keyless/envelopes-report.json --markdown out/v21b-keyless/compare.md
```

(`orgs.txt` must contain only 923609016.) What to read in the result:

| Question | Where | Good outcome |
|---|---|---|
| Is the 30 cap respected? | `operations.company_requests` | ≤ 30 plus mandatory requests |
| Is shared work visible? | `operations.shared_index_requests` | NAV requests listed separately |
| What was the stall? | `event_loop_lag.stalls[*].kind / cpu_share / top_frame / stack` | any stall over 3 s is now classified |
| More articles verified? | `verification.news.items_published`, article fetches | ≥ 5 published, fewer reasons of type "request limit" |
| News quality | `news.newsroom.rejected_reasons`, `candidates_merged_as_duplicates` | no event/conference pages published |
| Social | `accepted_linked_from_company_site`, claim confidence | confidence below 0.88 and ≤ website score unless sameAs |
| Coverage held | `verification.claims.available` | not below 244 |

Send me the three output files (`envelopes-report.json`, `envelopes.jsonl`, `envelopes-profiles.jsonl`) and I will complete this report: classify the stall and replace the offline evidence with live results.
