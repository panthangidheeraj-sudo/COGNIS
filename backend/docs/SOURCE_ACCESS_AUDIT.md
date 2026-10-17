# Source-access audit (Task 5)

Rule applied to every source: it is used only if a person can call it **anonymously or with a free key that is created instantly**, with no paid plan, no card, no approval step and no restricted endpoint. Anything else is listed as *not used* and the product shows that area as **unavailable**, never as "none found".

> **Honest limit of this audit.** It was written from the providers' official documentation. The environment this was built in could not reach any of these hosts, so **no endpoint was called live** while writing it. Behaviour was tested offline against recorded fixtures. Run `run_live_checks.cmd` on your machine to confirm each endpoint live.

| Domain | Source | Endpoint | Cost / credentials / approval | Used? | Permitted use | If unavailable |
|---|---|---|---|---|---|---|
| A. Structure | Enhetsregisteret (BRREG) | `data.brreg.no/enhetsregisteret/api/enheter/{org}`, `/underenheter/{org}`, `/roller` | Free, anonymous, NLOD 2.0 | Yes | Open data, attribution | Area shows *unavailable*; saved record used |
| A. Structure | BRREG konsernstruktur | `data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}` | Free, anonymous | Yes | As above | Parent/subsidiary rows omitted |
| A. Ownership | Skatteetaten shareholder register | by formal request | Needs an application | **No** | n/a | *Unavailable*: shareholders and ownership shares are never inferred |
| B. Financials | Regnskapsregisteret, open part | `data.brreg.no/regnskapsregisteret/regnskap/{org}` | Free, anonymous, NLOD 2.0; open part is the latest filed key figures | Yes | Open data | *Not reported* if nothing is filed; *unavailable* on error |
| B. Financials | Regnskapsregisteret, closed part | public-authority access | Restricted | **No** | n/a | not attempted |
| C. Contracts | TED Search API | `POST api.ted.europa.eu/v3/notices/search` | Free, anonymous | Yes | EU open data | *Unavailable*; no fallback invented |
| C. Contracts | Doffin open data (DFØ via data.norge.no) | downloadable dataset, imported with `scripts/import_doffin_open_data.py` | Free, anonymous download, manual import | Yes, once imported | Open data | *Not checked* until imported |
| C. Contracts | Doffin live API | subscription API | Needs a paid/approved subscription | **No** | n/a | not attempted |
| D. News | Company newsroom pages | the company's own verified website | Free; robots.txt respected | Yes | Short passage + link | *Not checked* |
| D. News | Tavily Search | `api.tavily.com/search` | Free plan, free key, no card; monthly credit allowance | Yes, candidates only | Search results are leads, never evidence; each page is fetched and identity-checked | On quota exhaustion (HTTP 432/429) search is switched off for the run: *unavailable*, **no paid fallback or upgrade** |
| E. Regulation | Official regulator pages (allowlist in `REGULATORY_DOMAINS`) | public pages found through Tavily, fetched by COGNIS | Free; robots.txt respected | Yes | Title, date, short passage, link | *Unavailable* if search is down |
| E. Patents/trademarks/designs | Patentstyret | `developer.patentstyret.no` API; `search.patentstyret.no` | API needs registration and a subscription key; the public search is a JavaScript app with no documented anonymous endpoint | **No** | n/a | Reported as *unavailable* with the reason |
| AI | Groq | OpenAI-compatible chat API | Free key, free allowance (rate limited); server-side only | Yes | Writes answers from supplied evidence only | Falls back to an evidence-only answer, labelled as such |
| Excluded | Google CSE, Proff, LinkedIn, paid Doffin | — | Paid, restricted or terms-prohibited | **No** | n/a | n/a |

## Official references
- Enhetsregisteret API: https://data.brreg.no/enhetsregisteret/api/docs/index.html
- Regnskapsregisteret: https://www.brreg.no/produkter-og-tjenester/data-og-api/regnskapsregisteret/ (open part anonymous; closed part for public authorities)
- TED Search API: https://docs.ted.europa.eu/api/latest/search.html
- Doffin open data: https://data.norge.no/datasets/a77b0408-85f9-3e12-8a66-8d500b492e9d
- Tavily credits and plans: https://docs.tavily.com/documentation/api-credits
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Patentstyret API portal: https://developer.patentstyret.no/

## How "free only" is enforced in code
- No code path starts a paid call. On a search refusal or exhausted allowance the HTTP layer records `tripped["search"]`; the run continues on saved evidence and says so.
- Chat may use at most `CHAT_MAX_SEARCHES` searches per question, `CHAT_LOOKUP_MAX_PAGES` page reads and `CHAT_LOOKUP_TIMEOUT_SECONDS` seconds (targeted lookup, `app/api/chat_lookup.py`; permitted domains only: the company's own site, the news allowlist and, for regulatory questions, the regulator allowlist). Chat never starts the full research pipeline; per-company and per-run budgets already exist.
- Keys are read from the server environment only. No endpoint returns a key; the frontend has none (tested on both sides).
- Retrieved pages are untrusted text: wrapped as data, stripped of markup, never obeyed.

## Statuses used everywhere
`verified` · `no public results found in checked sources` (not proof of absence) · `not reported` · `not checked` · `unavailable`.
