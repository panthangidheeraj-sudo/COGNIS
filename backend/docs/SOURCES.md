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
| Job boards linked from the verified site | public pages, robots.txt respected | job postings (hiring organisation must match) | yes (company-linked) | on |
| Job pages found by search (Tavily) | candidates only; fetched like any page | postings on the verified domain or a known job-board host, once tied to the exact organisation and shown to be current | yes, after verification | when Tavily is configured |
| Norid RDAP | open API | domain-holder organisation number (identity signal) | identity signal only | on |
| Kartverket Geonorge | open API | map position for the UI | no (display) | on (API only) |
| Tavily Search | API key (free plan: 1,000 credits/month) | website candidates when the register lists none; job-page candidates (one search) when the company's own pages show no current opening | **never** (candidates only) | when key set |
| Groq / OpenAI-compatible LLM | API key | planning, reading verified pages, summaries | never on its own (quotes verified) | when key + model set |
| NAV Arbeidsplassen (pam-stilling-feed) | free official API; NAV's public token or a free private `NAV_FEED_TOKEN` | job ads whose employer resolves to the exact organisation (supplementary to the company's own pages) | yes (exact employer only) | on |
| TED Search API | free, anonymous | procurement notices that state the organisation number (EU-published, above-threshold) | yes (exact org. no. only) | on |
| Doffin open data (DFØ, data.norge.no) | open download, imported offline | procurement notices with buyer/supplier organisation numbers, labelled with the dataset period | yes (exact org. no. only) | used when imported |
| Fakt.no | API needs a paid Business or Enterprise plan | **not used** — no integration, no API key | — | not used |
| Proff.no | paid licence | **not used** — free registers cover it (see below) | — | not used |
| Doffin API | subscription key | **not used** — TED + Doffin open data instead | — | not used |
| Patentstyret | API with subscription | IP rights | — | off (`not_configured`) |
| Skatteetaten aksjonærregister | formal request only | — | — | reported `not_applicable` |
| LinkedIn, Meta, Glassdoor, Indeed | not permitted | only links published by a verified company site | link only | never scraped |
| Sector registers (Finanstilsynet, DiBK, …) | varies | routed by NACE code and reported | — | off pending access review |

## Proff → free official sources

COGNIS does not use Proff. Each capability is mapped to a free official source in `app/connectors/capabilities.py`
(tested):

| Capability | Free source | Status |
| --- | --- | --- |
| Identity, status, addresses, NACE, founding date, employees, contact | Enhetsregisteret (live API; bulk snapshot fallback) | covered |
| Foretaksregisteret details (share capital, statutory purpose, registration) | Enhetsregisteret API fields | covered |
| Board, CEO, chair, auditor, accountant | Enhetsregisteret roles API | covered |
| Establishments | Enhetsregisteret sub-units | covered |
| Group structure | Konsernstruktur + entity fields | partial (no ownership shares) |
| Key financial figures, ratios | Regnskapsregisteret (same period and currency only) | covered |
| Multi-year history | Regnskapsregisteret + filed annual-report copies | partial |
| Register announcements | change detection between COGNIS runs | partial |
| Job ads | company careers pages, linked job boards, NAV Arbeidsplassen | covered |
| Shareholders and ownership shares | — (Skatteetaten: formal request only) | **unavailable** |
| Credit rating, payment remarks | — (proprietary) | **unavailable** |
| Industry benchmarks | — (SSB publishes aggregates; used only for county classification) | **unavailable** |

Unavailable capabilities stay empty — never estimated or inferred.

## NAV job ads — exact employer resolution

NAV's feed is a continuous log of all ads without server-side search, so COGNIS keeps a local index of the feed
summaries (uuid, status, title, business name, municipality, last change; six-month window), synced incrementally
(`scripts/sync_nav_feed.py`, a background task while the API runs, and once per batch within 10 % of the batch's
request budget). For a company, ads whose business name carries its distinctive name tokens (or an establishment's
name) are candidates; each candidate is re-read from NAV and published only if the employer resolves exactly
(`app/identity/employer.py`):

1. the ad's organisation number is the company's, or one of its registered establishments, or a sub-unit whose
   register parent is the company;
2. without a number: the exact registered name **and** the identity-verified website domain or a registered address.

Everything else (another organisation's number, a name that only resembles, a name + municipality only) is kept as
an internal unverified candidate with its reason and never shown as hiring evidence. Inactive or deleted ads are never
published, are masked in the index and disappear from profiles (NAV's terms); contact persons are never stored.
Ads link to arbeidsplassen.nav.no and keep their published / updated / expiry dates. No NAV match is never treated as
"not hiring".

## Hiring data — which source says what

Hiring comes from free, permitted sources only. Fakt.no's API needs a paid plan and is not used.

1. **Company careers pages and the job boards they link to** (primary). Pages of the identity-verified website: structured `JobPosting` data and job
   links on the careers page, plus the applicant-tracking page the site links to. robots.txt and rate limits apply; a refusal is recorded, never worked around.
2. **Search-assisted discovery** (Tavily, optional). When those pages show no current opening, one search asks for job pages on the verified domain or
   known job-board hosts. A hit is only a candidate: it is fetched, its `JobPosting` must tie itself to this exact organisation (it is on the verified
   domain, names the verified website, states the organisation number, or names the exact registered name and links to the verified website), and it must be
   current. Wrong-company, unverifiable, stale and closed pages are kept as internal candidates with the reason and never published. NAV's web pages, LinkedIn,
   Finn.no, Indeed and Glassdoor are never fetched.
3. **NAV Arbeidsplassen** (supplementary, see below).

**Current or stale.** A posting is current only while nothing says otherwise. A passed `validThrough`, a "closed" notice on the page (for example
"søknadsfristen er utløpt") or — with no end date — a posting/update date older than `JOB_MAX_AGE_DAYS` (180) makes it stale; a stale posting is never counted.
**Duplicates.** The same opening found on the company page, a job board and NAV is merged (same listing address, or same title in the same place, dates not
contradicting) and counted once. The merged entry keeps every listing's URL, published / updated dates and status; if listings disagree the most cautious status wins.

**Outcomes.** Each profile states exactly one:

| Outcome | Meaning |
| --- | --- |
| Verified openings | at least one verified, current opening (any source that could not be checked is listed as a caveat) |
| No verified openings found | the sources were checked and returned none — says nothing about whether the company is hiring |
| Source unavailable | a source could not be reached or read (timeout, refusal, robots.txt) — no conclusion |
| Research incomplete | the sources were not all checked (no verified website, budget/time limit, NAV index still catching up) — no conclusion |

Missing data is never read as "not hiring". A "0 open positions" is published only from the company's own explicit statement, and is withheld while a source
was unavailable. A NAV timeout ends the NAV step after `NAV_STEP_TIMEOUT_SECONDS` (20 s; each request is capped at `NAV_REQUEST_TIMEOUT_SECONDS`, 8 s, with one retry, and an unreachable NAV is not asked again for `NAV_UNAVAILABLE_COOLDOWN_SECONDS`) or two unreachable responses in a row and is shown as "NAV could not
be checked"; it never removes or lowers what the company's own pages established.

## Recent activity — what is read, in what order, and what is kept

Order of sources for company announcements (`connectors/newsroom.py`, then `connectors/news_discovery.py`):

1. **The company's own newsroom and investor-relations pages**, on the identity-verified website only: pages the site crawl already read, then newsroom / investor pages linked from the site, then the sitemap, then a few
   common paths (`/news`, `/nyheter`, `/investors` …) only if the site links none. Dated items are read from listings (`<time>`, printed dates, table rows) and from JSON-LD `NewsArticle` data.
2. **RSS / Atom feeds** that those pages advertise (same site only, at most two).
3. **Reputable secondary sources** found by search (Tavily, restricted to `SECONDARY_NEWS_DOMAINS`: business and trade press, wire services, exchange notices). Search results are *candidates*: every article is fetched,
   dated, and tied to this exact organisation before it is used (organisation number on the page; or the exact registered name in the headline plus a link to the verified website; or the exact registered name in the
   headline, unless that name continues into a longer one — "Autobjørn Bergen AS" is a different company; a page stating another organisation's number is rejected; generic names are not searched at all).
4. **Registers**: Enhetsregisteret (registration, establishments, group, name changes) and procurement notices (TED, Doffin). Register entries are always `routine` or `relevant`, never `major`.

Rules that apply:

* `robots.txt`, the SSRF policy, per-host rate limits and request budgets apply to every request. A page that robots.txt disallows is never fetched and is recorded as blocked; no login, CAPTCHA or paywall is bypassed.
* What is stored: the headline, the publication date, the link, and a short verbatim lead of at most 300 characters (the headline alone when the page says `nosnippet`). Article bodies are not stored.
* The same announcement found in several places is shown once with all its sources; the company's own words (investor relations, then newsroom) are the primary source, press coverage is last. Different figures or people are
  different announcements. TED and Doffin notices with the same notice id are one event.
* Every event needs a valid date (not in the future), a source URL and an evidence excerpt; news-like events also need their headline inside that excerpt. Anything else is excluded and counted in the section.
* A source that could not be read, a search that returned nothing, an unconfigured search key, a script-rendered newsroom — each is shown as a limitation of the research. None of them is read as "nothing happened".
* Classification (`app/events/`): Major / Relevant / Routine from the wording of the announcement (Norwegian and English), a stated amount and — only in the same currency — its size against the latest filed revenue,
  the type of source and recency. Currencies are never assumed or converted ("kroner" and "$" are not currency codes). Every event stores the reasons for its tier.

## Public procurement — coverage

* **TED** holds notices published in the EU's Official Journal: Norwegian *above-threshold* procurements. Below-threshold
  notices published only on Doffin are not in TED, so TED data is never presented as complete Norwegian coverage.
* **Doffin open data** is DFØ's periodically published dataset (yearly files). Import with
  `python scripts/import_doffin_open_data.py <files>`; facts carry the dataset period. Columns are matched by name;
  a bare "organisasjonsnummer" column without a buyer/supplier role is ignored unless mapped explicitly (`--map`).
* A notice is attached to a company only when the company's organisation number appears in the identifier of the
  role (supplier/winner or buyer). Name-only notices are kept as unverified candidates.

Rules that apply to every source:

* Every published claim cites an evidence record with source URL, retrieval time, SHA-256 of the
  fetched bytes, the exact span and the extraction method.
* A blocked request (robots.txt, 401/403, budget) is recorded as `blocked`; the agent never tries to
  bypass access controls, CAPTCHAs or logins.
* Cached responses keep their original retrieval time and hash — a cached answer is never presented
  as freshly retrieved.

## Version 2 — identity, social, news and trend rules (accuracy before coverage)

**Websites.** Where a candidate came from is never proof. A site that Enhetsregisteret lists, a domain that matches the registered e-mail address and a domain that
contains a brand word are recorded as *context signals* (`audit.context_signals`) and add nothing to the score. A site is published as the company's own only on
evidence the site or the domain registry provides: the organisation number on the site, the Norid domain holder being this organisation number, or the exact legal
name together with another registered identifier (address, phone or e-mail) — 0.65 for a register-linked candidate, 0.75 for any other. A site that presents the
parent group, or lists several legal entities with their organisation numbers, is a group website (`audit.scope = "group"`) and is not published as the individual
company's unless Norid names the company as the holder. Every attempt stores its signals, conflicts and plain-language `reasons`.

**Keyless discovery.** With no search API the agent still looks beyond the register: after the register-listed and e-mail-domain candidates it tries up to four
name-derived domains (`connectors/domain_discovery.py`: e.g. `autobjorn.no`, `autobjorn.com`; never for generic names). A guess is only a candidate: it is fetched
(robots.txt respected) and must pass the same gate; unreachable guesses are diagnostics, not the website module.

**Social profiles.** A footer link is a candidate. `identity/social.py` accepts it only when the handle carries the registered name or the verified domain's brand,
and rejects the network's own pages, web-agency / theme / platform links, the parent group and another country's group page. Profile pages are **not** fetched
(the networks forbid automated reads; LinkedIn is never fetched), so only the handle can be judged; unverified and rejected candidates stay in `diagnostics.social_candidates`.

**News.** An item is published only with a real article URL (not a bare domain, section/listing/archive/tag/pagination page, navigation or product page, file or
share link, nor the listing it was read from), a meaningful headline, and a genuine *publication* date (`datePublished`, `article:published_time`, RSS `pubDate`, a
printed date on the item). `dateModified`, `dateCreated`, RSS `updated`, modified `<time>` elements and the retrieval date are never used. Press articles also need
readable article text and must name this exact company. Rejections are kept with their reasons (`diagnostics.news_rejected`). Press discovery still needs a search
API: without one the report says press coverage was not checked, never that none exists.

**Trends.** `agent/trends.py` builds multi-year revenue, operating-profit and net-income series from published accounts claims: one accounting basis (company or
consolidated, never mixed), full twelve-month periods, one filing currency (no conversion), gaps shown, percentages only from a positive base. No model is involved.
Employees are not trended: the register states only the current headcount.

**Network failures.** A host whose `robots.txt` cannot be retrieved is still treated as off limits (RFC 9309), but is now recorded as the network failure it is
(`network`, `timeout`, `server_error`), not as "disallowed by robots.txt".
