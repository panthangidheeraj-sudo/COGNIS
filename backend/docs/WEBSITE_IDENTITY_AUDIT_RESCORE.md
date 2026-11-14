# Website identity: false-positive audit for the Signalpost re-score

Status: written 14 November 2026 against application candidate `ea05bf8` plus the uncommitted changes listed at the end. Every case below was produced by running the
real identity code and the real research pipeline against **synthetic fixture pages** (`backend/tests/test_signalpost_rescore_identity.py`). The fixtures reproduce the
structure of the two failing sites; they are not captures of gbbl.no or styrerommet.no, and no live site, register or search service was contacted for this audit.
The official evaluator alone can establish the accuracy of a run.

## What went wrong

The evaluator checked 29 claims on commit `408d9a4`: 17 correct, 12 about another company (59%). Two examples:

| Organisation | Wrong website | What that site really is |
| --- | --- | --- |
| VESTSIDEN HAGEBY IV BORETTSLAG (888078622) | gbbl.no | Grenland Boligbyggelag, the housing association that manages the cooperative |
| ALFHEIM 25-39 EIERSEKSJONSSAMEIE (891990472) | styrerommet.no | an OBOS board-portal platform |

Failure class: a **name, address, telephone number or e-mail address found somewhere on a page was treated as proof that the site belongs to the entity.** A manager or
portal lists the cooperatives it serves, usually with the manager's own contact details, and a cooperative's registered address / telephone / e-mail are very often the
manager's. In version 2 of the matcher a register-linked site reached the 0.65 threshold with the legal name (0.35) plus the registered address (0.30) or telephone (0.30), so a
customer list plus a shared office address was enough. The same weakness applied to any site that lists a company (a group page, a directory, a management firm's customer list).

## Claim-publication checklist (website-derived claims)

A site is published as the entity's website, and anything derived from it (`official_website`, `business_description`, contact details, social profiles, news, jobs) is
published, only when all of these hold. They are enforced in `audit_site` (`backend/app/identity/match.py`); a failed critical check means nothing is published.

1. **Exact legal entity.** The site presents itself as this entity: its legal name (or all distinctive name words, or structured-data `Organization` name) is in the title, site
   name, main headings, footer or structured data. A name inside a paragraph, list or table does not count.
2. **Exact organisation number or domain holder.** The organisation number appears in the site's own identity zone (footer, structured data, or a page that presents the entity), or
   Norid names this exact organisation as domain holder. An organisation number in a member list does not count. Cooperatives, sameier and eierseksjonssameier (`BRL`, `ESEK`, `SAM`
   or such a name) need this; contact details alone never verify them.
3. **Not a manager, parent, directory, portal or group.** Rejected or left ambiguous when the site presents itself as a boligbyggelag / forretningsfører / forvaltning /
   styreportal / beboerportal, lists three or more other housing entities, is a known directory or register, shows another organisation number, is held by another organisation at
   Norid, or presents the parent group.
4. **Contact details are corroboration only.** Registered address, telephone and e-mail count only on a site that presents the entity. On any other site they are recorded under
   `shared_signals` ("found but not counted") and never scored. The registry-listed URL and an e-mail domain only say where a candidate came from.
5. **Evidence URL is the original page.** Unchanged: every published claim cites the page it was read from; news cites the article page itself.

If any dependent claim's site is not verified, the website step publishes nothing from it (unchanged), and the register-listed URL is **withheld** (see below).

## Audit: accepted, rejected and ambiguous candidates

Synthetic fixtures; the decision, scope and first reason come from the real matcher.

| Candidate (fixture) | Decision | Scope | Why |
| --- | --- | --- | --- |
| gbbl.no-style manager, register-listed, lists the cooperative with the manager's shared address and telephone | ambiguous | manager | site presents itself as a boligbyggelag, not as the cooperative; address and telephone recorded as shared, not scored |
| styrerommet.no-style board portal, candidate from the registered e-mail domain | ambiguous | manager | site presents itself as a board portal; the e-mail domain is context only |
| manager that lists only this cooperative with its organisation number | ambiguous | manager | the number is in a list, not in the site's identity |
| same manager, but Norid names the manager as domain holder | rejected | manager | the domain registry names another organisation |
| proff.no page with the exact name and organisation number | rejected | directory | a directory describes many companies |
| cooperative's own page: name in title and headings, registered address and telephone, no organisation number | ambiguous | company | cooperatives need the organisation number or the Norid holder; contact details are not enough |
| cooperative's own page: organisation number in the footer | **accepted** | company | exact organisation number in the site's own identity |
| cooperative's own page: Norid holder is the cooperative | **accepted** | company | domain registry names this exact entity |
| AS: group / management page listing the company with its address, telephone and e-mail | ambiguous | company | the page does not present the company; all three contact details recorded as shared |
| AS: corporate site, name in title / footer and the registered address | **accepted** | company | presents the entity and a registered address corroborates it |
| AS: organisation number in the footer | **accepted** | company | exact organisation number in the site's own identity |

Through the full pipeline (keyless competition settings, offline fixtures) the two exact cases give: no `official_website`, no `registered_website`, no `website_title` /
`business_description` / contact / social / news / job claim; `official_website` is reported as `ambiguous` with no value; the website attempt is `ambiguous` with scope `manager`.

## Old versus new matcher (same synthetic pages, 14 cases)

Run through the matcher at `ea05bf8` and through the current one (`audit_site`, registry-linked candidate). Pinned in `backend/tests/test_signalpost_rescore_false_negatives.py`.

| Case | Old | New |
| --- | --- | --- |
| legal name in title / heading / footer only (AS) | ambiguous (0.55) | ambiguous (0.55), unchanged: a name alone is below 0.65, existing conservative behaviour, not a regression |
| legal name in JSON-LD only | ambiguous | ambiguous |
| name + registered address, or name + registered telephone | verified | verified |
| name + different contact details | ambiguous | ambiguous |
| JSON-LD `Organization` name + registered address | ambiguous | **verified** (the entity's own structured data now counts as the legal name, 0.35 + 0.30) |
| manager lists the cooperative with shared address / telephone / e-mail | **verified (1.50), the failure** | ambiguous |
| cooperative's own page: name + shared contact, no organisation number | verified | ambiguous (documented coverage trade-off) |
| organisation number only in another company's customer table | **verified, wrong company** | ambiguous |
| similar-named entity (Autobjørn Bil AS) / generic name collision (Nord Invest AS vs NORD AS) | ambiguous | ambiguous |
| organisation number in the site's footer | verified | verified |

Zero website claims is the correct result whenever identity is not established; the coverage loss is limited to the two "verified to ambiguous" patterns that were wrong-company risks.

## The register-listed URL

For these entities the register often lists the manager's site. "The register lists X" is true, but published as a website claim it reads as the wrong company's website. When the
audit shows the site belongs to another party (`other_party`: a manager, portal, directory, other domain holder, or another organisation number), the `registered_website` claim is
**withheld** and reported as an absence with the note that a listed website belongs to another party. The domain and the full reasons stay in `website_attempts` and the identity
diagnostics. A site that is merely unverified is not withheld. The profile's website section does not show the other party's domain or URL.

## Summary opening (no LLM)

The deterministic summary now leads with one source-attributed buyer-relevant fact, with its evidence ids, in this order: multi-year revenue trend, latest filed result, the company's
own verified description, a dated company announcement, a public-procurement award, a current job posting. Example from the fixture company: "According to its filed accounts
(Regnskapsregisteret), revenue fell from NOK 29.8M in FY2023 to NOK 21.8M in FY2025 (−26.9% overall), with FY2024 at NOK 26.5M." When none is verified, the opening says that no
buyer-relevant signal was established in the sources checked and cites no evidence; it does not fall back to registry fields. The registry sentence follows the lead. A model
summary that opens with registry fields is rejected and replaced by the deterministic one.

## Known limits and risks

* **Not verified against the live sites.** gbbl.no, styrerommet.no and the registers could not be reached from the build environment. The live keyless run of the two organisations
  has to be done on a machine with network access (commands in the submission notes).
* **Heuristics.** The manager / portal detection uses word markers and a member-list rule. A manager whose site shows none of the markers and lists fewer than three entities is
  still stopped by the "presents the entity" rule and, for cooperatives, by the organisation-number rule, but a corporate (AS) manager that names itself like the entity is not caught.
* **Coverage trade-off.** Sites that show only the name in body text plus the registered address, and cooperative sites that show no organisation number, are now ambiguous instead of
  verified. This lowers website coverage for those entities by design; the effect on the 100-company sample has not been measured.
* **Registry facts remain.** `registered_email` and `registered_phone` are published as register facts; a cooperative's register e-mail can be on the manager's domain.
* Missing, blocked or unavailable sources remain unavailable / incomplete, never zero. NAV remains partial in keyless runs unless the job-ad index is complete.

## Changed files

`backend/app/identity/match.py`, `backend/app/agent/orchestrator.py`, `backend/app/agent/buyer_signal.py` (new), `backend/app/agent/prompts.py`, `backend/app/evidence/gate.py`,
`backend/app/connectors/website.py`, `backend/app/competition/envelope.py`, `backend/app/api/profile_builder.py`, `backend/tests/test_currency.py` (one assertion updated for the new
summary wording), `backend/tests/test_signalpost_rescore_identity.py` (new), `backend/tests/test_signalpost_rescore_summary_and_sources.py` (new), `backend/tests/test_signalpost_rescore_false_negatives.py` (new), and this document. `backend/app/identity/match.py` also counts an `Organization` name in the entity's own structured data as the legal name.
