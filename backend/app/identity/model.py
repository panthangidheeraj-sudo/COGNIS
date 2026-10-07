"""Canonical company identity, anchored in Brønnøysundregistrene."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.util import clean_ws, date_only, normalize_currency, title_case_no
from ..security.urls import normalize_website

# County (fylke) from the first two digits of the municipality number — SSB KLASS 104, 2024 structure.
COUNTIES = {
    "03": "Oslo", "11": "Rogaland", "15": "Møre og Romsdal", "18": "Nordland", "31": "Østfold", "32": "Akershus", "33": "Buskerud",
    "34": "Innlandet", "39": "Vestfold", "40": "Telemark", "42": "Agder", "46": "Vestland", "50": "Trøndelag", "55": "Troms", "56": "Finnmark",
    "21": "Svalbard", "22": "Jan Mayen",
    # pre-2024 numbers that may still appear in frozen snapshots
    "30": "Viken", "38": "Vestfold og Telemark", "54": "Troms og Finnmark",
}

LEGAL_FORMS = {
    "AS": "Private limited company (AS)", "ASA": "Public limited company (ASA)", "ENK": "Sole proprietorship (ENK)",
    "ANS": "General partnership (ANS)", "DA": "Partnership with shared liability (DA)", "NUF": "Norwegian branch of a foreign company (NUF)",
    "SA": "Cooperative (SA)", "STI": "Foundation (STI)", "FLI": "Association (FLI)", "BRL": "Housing cooperative (BRL)",
    "KS": "Limited partnership (KS)", "SF": "State-owned enterprise (SF)", "IKS": "Inter-municipal company (IKS)", "KF": "Municipal enterprise (KF)",
    "ORGL": "Organisational unit (ORGL)", "STAT": "State (STAT)", "KOMM": "Municipality (KOMM)", "FYLK": "County authority (FYLK)",
    "BBL": "Housing association (BBL)", "ESEK": "Condominium (ESEK)", "SAM": "Co-ownership (SAM)", "PK": "Pension fund (PK)",
    "VPFO": "Securities fund (VPFO)", "BA": "Company with limited liability (BA)", "PRE": "Shipping partnership (PRE)", "KIRK": "Church of Norway (KIRK)",
}


def county_for(municipality_number: str | None) -> str | None:
    if not municipality_number or len(municipality_number) < 2:
        return None
    return COUNTIES.get(municipality_number[:2])


def format_address(addr: dict | None) -> str:
    if not isinstance(addr, dict):
        return ""
    lines = [clean_ws(x) for x in (addr.get("adresse") or []) if clean_ws(x)]
    place = " ".join(x for x in (addr.get("postnummer"), title_case_no(addr.get("poststed"))) if x)
    country = addr.get("land") if addr.get("landkode") not in (None, "NO") else None
    return ", ".join([*lines, place, *( [country] if country else [])]).strip(", ")


@dataclass
class CanonicalIdentity:
    org_number: str
    legal_name: str | None = None
    legal_form: str | None = None
    legal_form_description: str | None = None
    status: str = "unknown"  # active | bankruptcy | under_liquidation | forced_dissolution | deleted | unknown
    status_label: str | None = None
    business_address: dict = field(default_factory=dict)
    postal_address: dict = field(default_factory=dict)
    municipality: str | None = None
    municipality_number: str | None = None
    county: str | None = None
    industry_code: str | None = None
    industry_label: str | None = None
    secondary_industries: list[dict] = field(default_factory=list)
    founded: str | None = None
    registered_at: str | None = None
    business_register_at: str | None = None
    website: str | None = None
    website_raw: str | None = None
    email: str | None = None
    phone: str | None = None
    employees: int | None = None
    employees_registered: bool | None = None
    employees_as_of: str | None = None
    latest_accounts_year: str | None = None
    in_group: bool | None = None
    parent_unit: str | None = None
    former_names: list[dict] = field(default_factory=list)
    purpose: str | None = None
    activity: str | None = None
    sector: str | None = None
    vat_registered: bool | None = None
    business_registered: bool | None = None
    share_capital: dict | None = None
    deleted_at: str | None = None
    source: str = "live"  # live | bulk | none
    source_url: str | None = None
    retrieved_at: str | None = None
    content_sha256: str | None = None

    @property
    def found(self) -> bool:
        return bool(self.legal_name)

    @property
    def municipality_display(self) -> str | None:
        return title_case_no(self.municipality) if self.municipality else None

    @property
    def address_line(self) -> str:
        return format_address(self.business_address) or format_address(self.postal_address)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalIdentity:
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _status(body: dict) -> tuple[str, str]:
    if body.get("slettedato"):
        return "deleted", f"Deleted from the register {date_only(body.get('slettedato')) or ''}".strip()
    if body.get("konkurs"):
        return "bankruptcy", "Bankruptcy proceedings (konkurs)"
    if body.get("underTvangsavviklingEllerTvangsopplosning"):
        return "forced_dissolution", "Under compulsory liquidation or dissolution"
    if body.get("underAvvikling"):
        return "under_liquidation", "Under liquidation (under avvikling)"
    return "active", "Active"


def identity_from_entity(org: str, body: dict, *, source_url: str, retrieved_at: str | None, content_sha256: str | None) -> CanonicalIdentity:
    status, label = _status(body)
    biz = body.get("forretningsadresse") or body.get("beliggenhetsadresse") or {}
    post = body.get("postadresse") or {}
    muni_number = biz.get("kommunenummer") or post.get("kommunenummer")
    muni = biz.get("kommune") or post.get("kommune")
    form = body.get("organisasjonsform") or {}
    industries = [body.get(k) for k in ("naeringskode2", "naeringskode3") if isinstance(body.get(k), dict)]
    employees = body.get("antallAnsatte")
    has_emp = body.get("harRegistrertAntallAnsatte")
    capital = body.get("kapital") if isinstance(body.get("kapital"), dict) else None
    purpose = " ".join(clean_ws(x) for x in (body.get("vedtektsfestetFormaal") or []) if x) or None
    activity = " ".join(clean_ws(x) for x in (body.get("aktivitet") or []) if x) or None
    return CanonicalIdentity(
        org_number=org,
        legal_name=clean_ws(body.get("navn")) or None,
        legal_form=form.get("kode"),
        legal_form_description=form.get("beskrivelse"),
        status=status,
        status_label=label,
        business_address=biz,
        postal_address=post,
        municipality=muni,
        municipality_number=muni_number,
        county=county_for(muni_number),
        industry_code=(body.get("naeringskode1") or {}).get("kode"),
        industry_label=(body.get("naeringskode1") or {}).get("beskrivelse"),
        secondary_industries=industries,
        founded=date_only(body.get("stiftelsesdato")),
        registered_at=date_only(body.get("registreringsdatoEnhetsregisteret")),
        business_register_at=date_only(body.get("registreringsdatoForetaksregisteret")),
        website=normalize_website(body.get("hjemmeside")),
        website_raw=body.get("hjemmeside"),
        email=(body.get("epostadresse") or None),
        phone=(body.get("telefon") or None),
        employees=int(employees) if isinstance(employees, (int, float)) and (has_emp is not False) else None,
        employees_registered=has_emp if isinstance(has_emp, bool) else (employees is not None),
        employees_as_of=date_only(body.get("registreringsdatoAntallAnsatteEnhetsregisteret")),
        latest_accounts_year=str(body.get("sisteInnsendteAarsregnskap")) if body.get("sisteInnsendteAarsregnskap") else None,
        in_group=body.get("erIKonsern") if isinstance(body.get("erIKonsern"), bool) else None,
        parent_unit=body.get("overordnetEnhet"),
        former_names=[{"name": clean_ws(h.get("navn")), "from": date_only(h.get("fraDato")), "to": date_only(h.get("tilDato"))} for h in (body.get("historiskeNavn") or []) if h.get("navn")],
        purpose=purpose,
        activity=activity,
        sector=(body.get("institusjonellSektorkode") or {}).get("beskrivelse"),
        vat_registered=body.get("registrertIMvaregisteret") if isinstance(body.get("registrertIMvaregisteret"), bool) else None,
        business_registered=body.get("registrertIForetaksregisteret") if isinstance(body.get("registrertIForetaksregisteret"), bool) else None,
        share_capital={"amount": capital.get("belop"), "currency": normalize_currency(capital.get("valuta")), "type": capital.get("type")} if capital and capital.get("belop") is not None else None,
        deleted_at=date_only(body.get("slettedato")),
        source="live",
        source_url=source_url,
        retrieved_at=retrieved_at,
        content_sha256=content_sha256,
    )


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "ja", "yes"}


def identity_from_bulk(row: dict[str, Any], *, source_url: str, retrieved_at: str | None, content_sha256: str | None) -> CanonicalIdentity:
    """Bulk rows come either from the BRREG CSV download or the Signalpost universe JSONL."""
    raw = row.get("raw") or {}

    def pick(*names: str) -> Any:
        for name in names:
            for container in (row, raw):
                value = container.get(name)
                if value not in (None, ""):
                    return value
        return None

    org = str(pick("organisation_number", "organisasjonsnummer") or "")
    employees = pick("employees", "antallAnsatte")
    try:
        employees_int = int(employees) if employees not in (None, "") else None
    except (TypeError, ValueError):
        employees_int = None
    bankrupt = _truthy(pick("bankrupt", "konkurs"))
    liquidating = _truthy(pick("liquidating", "underAvvikling"))
    forced = _truthy(pick("underTvangsavviklingEllerTvangsopplosning"))
    deleted = pick("slettedato")
    if deleted:
        status, label = "deleted", "Deleted from the register"
    elif bankrupt:
        status, label = "bankruptcy", "Bankruptcy proceedings (konkurs)"
    elif forced:
        status, label = "forced_dissolution", "Under compulsory liquidation or dissolution"
    elif liquidating:
        status, label = "under_liquidation", "Under liquidation (under avvikling)"
    else:
        status, label = "active", "Active"
    muni_number = pick("municipality_number", "forretningsadresse.kommunenummer", "postadresse.kommunenummer")
    address_lines = [x for x in [pick("forretningsadresse.adresse")] if x]
    business_address = {
        "adresse": address_lines,
        "postnummer": pick("forretningsadresse.postnummer"),
        "poststed": pick("forretningsadresse.poststed"),
        "kommune": pick("municipality", "forretningsadresse.kommune"),
        "kommunenummer": muni_number,
        "landkode": pick("forretningsadresse.landkode") or "NO",
    }
    business_address = {k: v for k, v in business_address.items() if v not in (None, "", [])}
    form = pick("legal_form", "organisasjonsform.kode")
    return CanonicalIdentity(
        org_number=org,
        legal_name=clean_ws(pick("name", "navn")) or None,
        legal_form=form,
        legal_form_description=pick("organisasjonsform.beskrivelse"),
        status=status,
        status_label=label,
        business_address=business_address,
        municipality=pick("municipality", "forretningsadresse.kommune"),
        municipality_number=muni_number,
        county=county_for(muni_number),
        industry_code=pick("industry_code", "naeringskode1.kode"),
        industry_label=pick("industry_label", "naeringskode1.beskrivelse"),
        founded=date_only(pick("stiftelsesdato")),
        registered_at=date_only(pick("registreringsdatoEnhetsregisteret")),
        website=normalize_website(pick("website", "hjemmeside")),
        website_raw=pick("website", "hjemmeside"),
        employees=employees_int,
        employees_registered=employees_int is not None,
        latest_accounts_year=str(pick("latest_submitted_accounts", "sisteInnsendteAarsregnskap") or "") or None,
        in_group=_truthy(pick("erIKonsern")) if pick("erIKonsern") is not None else None,
        source="bulk",
        source_url=source_url,
        retrieved_at=retrieved_at,
        content_sha256=content_sha256,
    )
