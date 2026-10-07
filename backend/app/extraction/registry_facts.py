"""Brønnøysund modules → candidate observations (deterministic, structured-field evidence)."""
from __future__ import annotations

from typing import Any

from ..core.util import clean_ws, date_only, normalize_currency, title_case_no
from ..evidence.models import ModuleResult, Observation
from ..identity.model import COUNTIES, LEGAL_FORMS, CanonicalIdentity, format_address

ROLE_FIELDS = {
    "DAGL": ("ceo", "CEO"),
    "LEDE": ("board_chair", "Chair of the board"),
    "NEST": ("deputy_chair", "Deputy chair"),
    "MEDL": ("board_member", "Board member"),
    "VARA": ("deputy_board_member", "Deputy board member"),
    "OBS": ("board_observer", "Board observer"),
    "KONT": ("contact_person", "Contact person"),
    "REVI": ("auditor", "Auditor"),
    "REGN": ("accountant", "Accountant"),
    "FFØR": ("business_manager", "Business manager"),
    "INNH": ("proprietor", "Proprietor"),
    "DTPR": ("partner", "Partner (joint liability)"),
    "DTSO": ("partner", "Partner (shared liability)"),
    "KOMP": ("general_partner", "General partner"),
    "SAM": ("co_owner", "Co-owner"),
    "REPR": ("norwegian_representative", "Norwegian representative"),
    "KDEB": ("bankruptcy_debtor", "Bankruptcy debtor"),
    "BOBE": ("estate_administrator", "Estate administrator"),
}

FINANCIAL_FIELDS: list[tuple[str, str, str, str]] = [
    # (record key, claim field, label, Norwegian source path)
    ("revenue", "revenue", "Revenue", "resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter"),
    ("operating_expenses", "operating_expenses", "Operating expenses", "resultatregnskapResultat.driftsresultat.driftskostnad.sumDriftskostnad"),
    ("payroll_expenses", "payroll_expenses", "Payroll expenses", "resultatregnskapResultat.driftsresultat.driftskostnad.loennskostnad"),
    ("operating_result", "operating_result", "Operating result", "resultatregnskapResultat.driftsresultat.driftsresultat"),
    ("net_financial_items", "net_financial_items", "Net financial items", "resultatregnskapResultat.finansresultat.nettoFinans"),
    ("profit_before_tax", "profit_before_tax", "Profit before tax", "resultatregnskapResultat.ordinaertResultatFoerSkattekostnad"),
    ("tax_expense", "tax_expense", "Tax expense", "resultatregnskapResultat.ordinaertResultatSkattekostnad"),
    ("annual_result", "annual_result", "Annual result", "resultatregnskapResultat.aarsresultat"),
    ("assets", "total_assets", "Total assets", "eiendeler.sumEiendeler"),
    ("fixed_assets", "fixed_assets", "Fixed assets", "eiendeler.anleggsmidler.sumAnleggsmidler"),
    ("current_assets", "current_assets", "Current assets", "eiendeler.omloepsmidler.sumOmloepsmidler"),
    ("cash", "cash_and_bank", "Cash and bank deposits", "eiendeler.sumBankinnskuddOgKontanter"),
    ("equity", "equity", "Equity", "egenkapitalGjeld.egenkapital.sumEgenkapital"),
    ("debt", "debt", "Total debt", "egenkapitalGjeld.gjeldOversikt.sumGjeld"),
    ("short_term_debt", "short_term_debt", "Short-term debt", "egenkapitalGjeld.gjeldOversikt.kortsiktigGjeld.sumKortsiktigGjeld"),
    ("long_term_debt", "long_term_debt", "Long-term debt", "egenkapitalGjeld.gjeldOversikt.langsiktigGjeld.sumLangsiktigGjeld"),
]


def period_label(start: str | None, end: str | None) -> str:
    if not end:
        return "FY?"
    if end.endswith("-12-31") and (not start or start.endswith("-01-01")) and (not start or start[:4] == end[:4]):
        return f"FY{end[:4]}"
    return f"FY{start[:4]}/{end[2:4]}" if start and start[:4] != end[:4] else f"FY{end[:4]} (to {end[5:]})"


def _base(mod: ModuleResult, **kw: Any) -> dict[str, Any]:
    return {
        "module": mod.module, "source_id": mod.source_id, "source_name": mod.source_name, "source_class": mod.source_class,
        "source_url": mod.url, "retrieved_at": mod.retrieved_at, "content_sha256": mod.content_sha256, "tier": mod.tier, **kw,
    }


def identity_observations(identity: CanonicalIdentity, mod: ModuleResult) -> list[Observation]:
    """Facts that come straight from the entity record (live API or bulk snapshot)."""
    if mod.state != "available" or not identity.found:
        return []
    obs: list[Observation] = []
    as_of = date_only(mod.retrieved_at)
    bulk = mod.module == "registry"
    method = "registry_bulk_row" if bulk else "structured_api"

    def add(field: str, value: Any, span: str, label: str, **kw: Any) -> None:
        if value in (None, "", [], {}):
            return
        obs.append(Observation(field=field, value=value, claim_span=span, extraction_method=method, label=label, as_of=kw.pop("as_of", as_of), **_base(mod), **kw))

    add("legal_name", identity.legal_name, f'navn = "{identity.legal_name}"', "Legal name")
    if identity.legal_form:
        add("legal_form", identity.legal_form, f'organisasjonsform.kode = "{identity.legal_form}"' + (f' ({identity.legal_form_description})' if identity.legal_form_description else ""),
            "Legal form", attributes={"description": LEGAL_FORMS.get(identity.legal_form, identity.legal_form_description)})
    status_span = {
        "active": "konkurs = false, underAvvikling = false",
        "bankruptcy": "konkurs = true",
        "under_liquidation": "underAvvikling = true",
        "forced_dissolution": "underTvangsavviklingEllerTvangsopplosning = true",
        "deleted": f"slettedato = {identity.deleted_at or '(deleted)'}",
    }.get(identity.status)
    if status_span:
        add("registration_status", identity.status, status_span, "Registration status", attributes={"label": identity.status_label})
    if identity.industry_code:
        add("industry_code", identity.industry_code, f'naeringskode1.kode = "{identity.industry_code}"', "Industry code (NACE/SN2007)")
    if identity.industry_label:
        add("industry_label", identity.industry_label, f'naeringskode1.beskrivelse = "{identity.industry_label}"', "Industry")
    for idx, extra in enumerate(identity.secondary_industries or [], start=2):
        if extra.get("kode"):
            add("secondary_industry", f'{extra.get("kode")} {extra.get("beskrivelse") or ""}'.strip(), f'naeringskode{idx} = {extra.get("kode")} ({extra.get("beskrivelse")})',
                "Secondary industry", key_suffix=str(extra.get("kode")))
    biz = format_address(identity.business_address)
    if biz:
        add("business_address", biz, f"forretningsadresse = {biz}", "Business address", attributes={"postal_code": (identity.business_address or {}).get("postnummer")})
    post = format_address(identity.postal_address)
    if post and post != biz:
        add("postal_address", post, f"postadresse = {post}", "Postal address")
    if identity.municipality:
        add("municipality", title_case_no(identity.municipality), f'kommune = "{identity.municipality}" (kommunenummer {identity.municipality_number})', "Municipality",
            attributes={"municipality_number": identity.municipality_number})
    if identity.county and identity.municipality_number:
        obs.append(Observation(field="county", value=identity.county, claim_span=f"kommunenummer {identity.municipality_number} → fylke {identity.municipality_number[:2]} {COUNTIES.get(identity.municipality_number[:2])} (SSB KLASS 104)",
                               extraction_method="derived_classification", label="County", as_of=as_of, **_base(mod)))
    add("founded_date", identity.founded, f"stiftelsesdato = {identity.founded}", "Founded")
    add("registration_date", identity.registered_at, f"registreringsdatoEnhetsregisteret = {identity.registered_at}", "Registered in Enhetsregisteret")
    add("business_register_date", identity.business_register_at, f"registreringsdatoForetaksregisteret = {identity.business_register_at}", "Registered in Foretaksregisteret")
    if identity.employees is not None:
        add("registered_employees", identity.employees, f"antallAnsatte = {identity.employees}", "Registered employees", unit="people", numeric=True,
            as_of=identity.employees_as_of or as_of)
    if identity.website:
        add("registered_website", identity.website, f'hjemmeside = "{identity.website_raw or identity.website}"', "Website listed in the register")
    if identity.email:
        add("registered_email", identity.email.lower(), f'epostadresse = "{identity.email}"', "Registered e-mail")
    if identity.phone:
        add("registered_phone", clean_ws(identity.phone), f'telefon = "{identity.phone}"', "Registered phone")
    if identity.vat_registered is not None:
        add("vat_registered", identity.vat_registered, f"registrertIMvaregisteret = {str(identity.vat_registered).lower()}", "VAT registered")
    if identity.business_registered is not None:
        add("in_business_register", identity.business_registered, f"registrertIForetaksregisteret = {str(identity.business_registered).lower()}", "Registered in Foretaksregisteret")
    if identity.share_capital and identity.share_capital.get("amount") is not None:
        capital_currency = normalize_currency(identity.share_capital.get("currency"))
        add("share_capital", float(identity.share_capital["amount"]),
            f'kapital.belop = {identity.share_capital["amount"]}' + (f" {capital_currency}" if capital_currency else " (valuta ikke oppgitt)"), "Share capital",
            unit=capital_currency, currency=capital_currency, numeric=True)
    for former in identity.former_names or []:
        add("former_name", former["name"], f'historiskeNavn: "{former["name"]}" ({former.get("from") or "?"} – {former.get("to") or "?"})', "Former name",
            key_suffix=former["name"], effective_from=former.get("from"), effective_to=former.get("to"), current=False)
    add("statutory_purpose", identity.purpose, f"vedtektsfestetFormaal = {identity.purpose}", "Statutory purpose")
    add("registered_activity", identity.activity, f"aktivitet = {identity.activity}", "Registered activity")
    add("institutional_sector", identity.sector, f"institusjonellSektorkode.beskrivelse = {identity.sector}", "Institutional sector")
    add("latest_filed_accounts_year", identity.latest_accounts_year, f"sisteInnsendteAarsregnskap = {identity.latest_accounts_year}", "Latest submitted annual accounts")
    if identity.in_group is not None:
        add("part_of_group", identity.in_group, f"erIKonsern = {str(identity.in_group).lower()}", "Part of a group")
    if identity.parent_unit:
        add("parent_unit", identity.parent_unit, f"overordnetEnhet = {identity.parent_unit}", "Parent unit (register)")
    return obs


def role_observations(mod: ModuleResult, roles: list[dict[str, Any]]) -> list[Observation]:
    if mod.state != "available":
        return []
    obs: list[Observation] = []
    for role in roles:
        if role.get("inactive") or role.get("deceased") or not role.get("name"):
            continue
        field, label = ROLE_FIELDS.get(role.get("role_code") or "", ("role_holder", role.get("role") or "Role"))
        ident = role.get("organisation_number") or role["name"]
        span = f'{role.get("group") or "Rolle"}: {role.get("role") or role.get("role_code")} — {role["name"]}' + (f" (org.nr {role['organisation_number']})" if role.get("organisation_number") else "")
        obs.append(Observation(
            field=field, value=role["name"], claim_span=span, extraction_method="structured_api", label=label, key_suffix=f"{role.get('role_code')}:{ident}",
            as_of=role.get("group_last_changed"), attributes={"role": role.get("role"), "role_code": role.get("role_code"), "group": role.get("group"),
                                                              "holder_type": role.get("kind"), "organisation_number": role.get("organisation_number"),
                                                              "group_last_changed": role.get("group_last_changed")},
            **_base(mod),
        ))
    return obs


def location_observations(mod: ModuleResult, locations: list[dict[str, Any]]) -> list[Observation]:
    if mod.state != "available":
        return []
    obs = [Observation(field="registered_establishment_count", value=len([x for x in locations if not x.get("deleted") and not x.get("closed")]),
                       claim_span=f"underenheter (overordnetEnhet) returned {len(locations)} establishment(s)", extraction_method="structured_api",
                       label="Registered establishments", numeric=True, as_of=date_only(mod.retrieved_at), **_base(mod))]
    for loc in locations:
        if loc.get("deleted") or loc.get("closed"):
            continue
        address = format_address(loc.get("address"))
        muni = title_case_no((loc.get("address") or {}).get("kommune"))
        value = f"{loc.get('name')} — {address}" if address else loc.get("name")
        obs.append(Observation(
            field="registered_establishment", value=value, claim_span=f"underenhet {loc.get('organisation_number')}: {loc.get('name')}, beliggenhetsadresse {address}",
            extraction_method="structured_api", label="Registered establishment", key_suffix=str(loc.get("organisation_number")),
            effective_from=loc.get("started"), as_of=date_only(mod.retrieved_at),
            attributes={"organisation_number": loc.get("organisation_number"), "name": loc.get("name"), "address": address, "municipality": muni,
                        "municipality_number": (loc.get("address") or {}).get("kommunenummer"), "postal_code": (loc.get("address") or {}).get("postnummer"),
                        "employees": loc.get("employees"), "industry": (loc.get("industry") or {}).get("beskrivelse")},
            **_base(mod),
        ))
    return obs


def group_observations(mod: ModuleResult, org: str) -> list[Observation]:
    body = mod.value if isinstance(mod.value, dict) else None
    if mod.state != "available" or not body:
        return []
    obs: list[Observation] = []
    top_org = body.get("organisasjonsnummer")
    top_name = clean_ws(body.get("navn"))
    nodes = body.get("children") or []

    def walk(items: list[dict]) -> list[dict]:
        out = []
        for item in items:
            out.append(item)
            out.extend(walk(item.get("children") or []))
        return out

    flat = walk(nodes)
    me = next((n for n in flat if n.get("organisasjonsnummer") == org), None)
    if me and me.get("parentOrganisasjonsnummer"):
        obs.append(Observation(field="parent_company", value=clean_ws(me.get("parentNavn")) or me["parentOrganisasjonsnummer"], key_suffix=me["parentOrganisasjonsnummer"],
                               claim_span=f'konsernstruktur: {me.get("knytningsform", {}).get("beskrivelse", "konsern")} av {me.get("parentNavn")} ({me["parentOrganisasjonsnummer"]}), grunnlag {me.get("grunnlag")}',
                               extraction_method="structured_api", label="Parent company", effective_from=date_only(me.get("dato")),
                               attributes={"organisation_number": me["parentOrganisasjonsnummer"], "relation": (me.get("knytningsform") or {}).get("beskrivelse"), "share": me.get("grunnlag")},
                               **_base(mod)))
        if top_org and top_org != me.get("parentOrganisasjonsnummer") and top_org != org:
            obs.append(Observation(field="ultimate_parent_company", value=top_name or top_org, key_suffix=top_org, claim_span=f"konsernstruktur topp: {top_name} ({top_org})",
                                   extraction_method="structured_api", label="Ultimate parent", attributes={"organisation_number": top_org}, **_base(mod)))
    for child in flat:
        if child.get("parentOrganisasjonsnummer") == org and child.get("organisasjonsnummer"):
            obs.append(Observation(field="subsidiary", value=clean_ws(child.get("navn")) or child["organisasjonsnummer"], key_suffix=child["organisasjonsnummer"],
                                   claim_span=f'konsernstruktur: {child.get("navn")} ({child["organisasjonsnummer"]}) — {(child.get("knytningsform") or {}).get("beskrivelse", "datter")}, grunnlag {child.get("grunnlag")}',
                                   extraction_method="structured_api", label="Subsidiary", effective_from=date_only(child.get("dato")),
                                   attributes={"organisation_number": child["organisasjonsnummer"], "relation": (child.get("knytningsform") or {}).get("beskrivelse"), "share": child.get("grunnlag")},
                                   **_base(mod)))
    return obs


def financial_observations(mod: ModuleResult) -> list[Observation]:
    records = (mod.raw or {}).get("records") if isinstance(mod.raw, dict) else None
    if mod.state != "available" or not records:
        return []
    obs: list[Observation] = []
    for rec in records:
        start, end = rec.get("period_start"), rec.get("period_end")
        if not end:
            continue
        consolidated = (rec.get("account_type") or "").upper() == "KONSERN"
        # The filing's own `valuta` is the only authority for what currency an amount is in. A missing or malformed code is
        # kept as "not stated" (None) — it is never replaced by an assumed NOK.
        currency = normalize_currency(rec.get("currency"))
        unit_text = f" {currency}" if currency else ""
        stated_note = "" if currency else ", valuta ikke oppgitt i regnskapet"
        label_period = period_label(start, end)
        interval = f"{start}/{end}" if start else end
        for key, field, label, path in FINANCIAL_FIELDS:
            value = rec.get(key)
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            claim_field = f"consolidated_{field}" if consolidated else field
            obs.append(Observation(
                field=claim_field, value=float(value),
                claim_span=f"{path} = {value:.0f}{unit_text} (regnskapsperiode {start}–{end}, regnskapstype {rec.get('account_type')}{stated_note})",
                extraction_method="structured_api", label=("Consolidated " + label.lower()) if consolidated else label, reporting_period=interval, period_label=label_period,
                unit=currency, currency=currency, numeric=True, current=True, effective_from=start, effective_to=end,
                attributes={"account_type": rec.get("account_type"), "unaudited": rec.get("unaudited"), "audit_opted_out": rec.get("audit_opted_out"),
                            "small_company": rec.get("small_company"), "journal_number": rec.get("journal_number"),
                            "currency_source": "regnskapsregisteret.valuta" if currency else "not_stated"},
                **_base(mod),
            ))
    return obs


def filing_history_observations(mod: ModuleResult) -> list[Observation]:
    value = mod.value if isinstance(mod.value, dict) else None
    if mod.state != "available" or not value:
        return []
    obs = []
    for pdf in value.get("pdfs") or []:
        year = pdf.get("year")
        obs.append(Observation(field="annual_accounts_filed", value=str(year), claim_span=f"årsregnskap (kopi) available for år {year}", extraction_method="structured_api",
                               label="Annual accounts filed", key_suffix=str(year), reporting_period=f"{year}-01-01/{year}-12-31", period_label=f"FY{year}",
                               attributes={"document_url": pdf.get("url")}, **_base(mod)))
    return obs
