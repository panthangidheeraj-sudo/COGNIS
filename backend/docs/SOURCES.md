# Sources, permissions and how each is used

Machine-readable manifest: `../sources.yaml`. Capability states are reported per company in the
envelope `modules` block and in `/api/status`.

| Source | Access | Used for | Evidence? | Default |
| --- | --- | --- | --- | --- |
| Enhetsregisteret (enheter, underenheter) | open API, NLOD 2.0 | identity, status, addresses, industry, employees, website field, e-mail, founded, former names, establishments | yes (primary) | on |
| Enhetsregisteret bulk snapshot | open download | identity fallback, corroboration, conflict detection | yes (primary, snapshot date) | when `--bulk` given |
| Enhetsregisteret roller | open API | CEO, board, auditor, accountant, proprietor | yes (primary) | on |
| Konsernstruktur | open API | parent, ultimate parent, subsidiaries | yes (primary) | on unless `erIKonsern=false` |
| Regnskapsregisteret | open API | company and consolidated accounts per period | yes (primary) | on |
| Årsregnskap (kopi) years | open API (rate-limited) | which years have filed reports | yes (primary) | on |
| Company website | public pages, robots.txt respected | official website, description, contact, social links, news, careers | yes, only after identity verification | on |
| Job boards linked from the verified site | public pages | job postings (hiring organisation must match) | yes (company-linked) | on |
| Norid RDAP | open API | domain-holder organisation number (identity signal) | identity signal only | on |
| Kartverket Geonorge | open API | map position for the UI | no (display) | on (API only) |
| Tavily Search | API key (free plan: 1,000 credits/month) | website candidates when the register lists none | **never** | when key set |
| Groq / OpenAI-compatible LLM | API key | planning, reading verified pages, summaries | never on its own (quotes verified) | when key + model set |
| Proff.no | licensed API | secondary financial cross-check | secondary | off (`not_configured`) |
| Doffin | API with subscription + review | public procurement | — | off (`not_configured`) |
| Patentstyret | API with subscription | IP rights | — | off (`not_configured`) |
| Skatteetaten aksjonærregister | formal request only | — | — | reported `not_applicable` |
| LinkedIn, Meta, Glassdoor, Indeed | not permitted | only links published by a verified company site | link only | never scraped |
| NAV arbeidsplassen feed | token, no org numbers in postings | — | — | off (cannot be matched safely) |
| Sector registers (Finanstilsynet, DiBK, …) | varies | routed by NACE code and reported | — | off pending access review |

Rules that apply to every source:

* Every published claim cites an evidence record with source URL, retrieval time, SHA-256 of the
  fetched bytes, the exact span and the extraction method.
* A blocked request (robots.txt, 401/403, budget) is recorded as `blocked`; the agent never tries to
  bypass access controls, CAPTCHAs or logins.
* Cached responses keep their original retrieval time and hash — a cached answer is never presented
  as freshly retrieved.
