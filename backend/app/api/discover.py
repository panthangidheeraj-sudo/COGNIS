"""Discover: natural-language interpretation → Enhetsregisteret search filters.

Interpretation is deterministic first (place names, sizes, years, statuses,
industry words); the LLM, when configured, can add filters but only with values
taken from the user's own words. Filters that need research data (revenue,
hiring, coverage) are applied to already-researched companies only, and the
result says so.
"""
from __future__ import annotations

import re
from typing import Any

from ..agent import llm_tasks
from ..core.util import fold, title_case_no
from ..identity.model import COUNTIES
from ..storage import repository as repo

# Major municipalities (2024 numbering) — the full list is fetched from Geonorge and cached.
MUNICIPALITIES: dict[str, str] = {
    "oslo": "0301", "bergen": "4601", "trondheim": "5001", "stavanger": "1103", "kristiansand": "4204", "tromsø": "5501", "tromso": "5501", "drammen": "3301",
    "fredrikstad": "3107", "sandnes": "1108", "bærum": "3201", "baerum": "3201", "asker": "3203", "lillestrøm": "3205", "lillestrom": "3205", "ålesund": "1508",
    "alesund": "1508", "bodø": "1804", "bodo": "1804", "sarpsborg": "3105", "skien": "4003", "tønsberg": "3905", "tonsberg": "3905", "haugesund": "1106",
    "moss": "3103", "porsgrunn": "4001", "arendal": "4203", "hamar": "3403", "larvik": "3909", "sandefjord": "3907", "halden": "3101", "lørenskog": "3222",
    "molde": "1506", "gjøvik": "3407", "lillehammer": "3405", "harstad": "5503", "kongsberg": "3303", "kristiansund": "1505", "narvik": "1806", "alta": "5601",
    "steinkjer": "5006", "horten": "3901", "ringsaker": "3411", "ullensaker": "3209", "nordre follo": "3207", "karmøy": "1149", "askøy": "4627", "øygarden": "4626",
    "bjørnafjorden": "4624", "sola": "1124", "time": "1121", "klepp": "1120", "hå": "1119", "stjørdal": "5035", "levanger": "5037", "namsos": "5007", "mo i rana": "1833",
    "rana": "1833", "hammerfest": "5603", "vik": "4639", "hol": "3330", "voss": "4621", "sogndal": "4640", "førde": "4647", "sunnfjord": "4647", "kinn": "4602",
    "elverum": "3420", "kongsvinger": "3401", "notodden": "4005", "grimstad": "4202", "mandal": "4204", "egersund": "1101", "eigersund": "1101", "orkland": "5059",
    "malvik": "5031", "melhus": "5028", "verdal": "5038", "ski": "3207", "jessheim": "3209", "frogn": "3214", "nesodden": "3212", "gran": "3446", "vestby": "3216",
}
COUNTY_NAMES = {fold(v): k for k, v in COUNTIES.items()}
INDUSTRY_WORDS: list[tuple[tuple[str, ...], str, str]] = [
    (("software", "programvare", "saas", "it-konsulent", "it consulting", "it-selskap", "tech", "teknologi"), "62", "Software and IT services"),
    (("consulting", "rådgivning", "konsulent", "management consulting"), "70.2", "Management consulting"),
    (("accounting", "regnskap", "revisjon", "audit"), "69.2", "Accounting and auditing"),
    (("law", "legal", "advokat", "jus"), "69.1", "Legal services"),
    (("construction", "bygg", "anlegg", "entreprenør", "builder"), "41", "Construction"),
    (("electrician", "elektro", "elektriker", "electrical"), "43.21", "Electrical installation"),
    (("plumbing", "rørlegger", "vvs"), "43.22", "Plumbing and heating"),
    (("seafood", "fish", "fiske", "sjømat", "aquaculture", "oppdrett", "havbruk", "laks", "salmon"), "03", "Fishing and aquaculture"),
    (("shipping", "rederi", "maritime", "maritim", "sjøfart"), "50", "Water transport"),
    (("energy", "energi", "kraft", "power", "renewable", "fornybar"), "35", "Electricity and energy supply"),
    (("oil", "olje", "petroleum", "gas", "offshore"), "06", "Oil and gas extraction"),
    (("real estate", "eiendom", "property", "properties"), "68", "Real estate"),
    (("restaurant", "café", "kafé", "cafe", "servering"), "56", "Food and beverage service"),
    (("hotel", "hotell", "overnatting"), "55", "Accommodation"),
    (("retail", "butikk", "detaljhandel", "store", "shop"), "47", "Retail trade"),
    (("wholesale", "engros", "agentur"), "46", "Wholesale trade"),
    (("transport", "logistics", "logistikk", "trucking", "freight", "spedisjon"), "49", "Land transport and logistics"),
    (("health", "helse", "clinic", "klinikk", "lege", "medical", "dental", "tannlege"), "86", "Health services"),
    (("engineering", "ingeniør", "architect", "arkitekt"), "71", "Architecture and engineering"),
    (("marketing", "reklame", "advertising", "markedsføring", "byrå", "agency"), "73", "Advertising and market research"),
    (("bank", "banking", "finance", "finans", "investment", "investering", "holding"), "64", "Financial services"),
    (("insurance", "forsikring"), "65", "Insurance"),
    (("telecom", "telekom", "telecommunications"), "61", "Telecommunications"),
    (("pharma", "legemiddel", "pharmaceutical"), "21", "Pharmaceuticals"),
    (("education", "utdanning", "school", "skole", "kurs", "training"), "85", "Education"),
    (("agriculture", "landbruk", "farm", "gård", "jordbruk"), "01", "Agriculture"),
    (("media", "medier", "publishing", "forlag", "film"), "58", "Publishing and media"),
    (("research", "forskning", "r&d", "biotech", "bioteknologi"), "72", "Scientific research"),
    (("car", "bil", "automotive", "motorvogn", "verksted"), "45", "Motor vehicle trade and repair"),
    (("cleaning", "renhold", "vaktmester", "facility"), "81", "Cleaning and facility services"),
    (("staffing", "bemanning", "recruitment", "rekruttering"), "78", "Employment services"),
]
STOP_WORDS = {"companies", "company", "selskaper", "selskap", "bedrifter", "firma", "in", "i", "with", "med", "and", "og", "the", "a", "an", "that", "som", "are", "er",
              "over", "under", "than", "more", "less", "employees", "ansatte", "founded", "after", "since", "etter", "registered", "located", "based", "find", "show",
              "list", "all", "hiring", "active", "aktive", "norwegian", "norske", "norway", "norge", "revenue", "omsetning", "million", "mill", "mnok", "nok", "billion",
              "from", "fra", "at", "least", "minst", "most", "før", "before", "to", "til", "of", "av", "for"}

ALLOWED_KEYS = {"location", "municipality", "industry", "status", "employeesMin", "employeesMax", "revenueMin", "revenueMax", "hiring", "coverageMin",
                "recentActivity", "foundedAfter"}
LABELS = {"location": "Location", "municipality": "Municipality", "industry": "Industry", "status": "Status", "employeesMin": "Employees from", "employeesMax": "Employees to",
          "revenueMin": "Revenue from", "revenueMax": "Revenue to", "hiring": "Hiring", "coverageMin": "Coverage from", "recentActivity": "Recent activity",
          "foundedAfter": "Founded after"}

FILTER_CAPABILITIES = [
    {"key": "municipality", "label": "Municipality or county", "type": "text"},
    {"key": "industry", "label": "Industry (words or NACE code)", "type": "text"},
    {"key": "status", "label": "Status", "type": "select", "options": [{"value": "active", "label": "Active"}, {"value": "bankruptcy", "label": "Bankruptcy"},
                                                                      {"value": "under_liquidation", "label": "Under liquidation"}]},
    {"key": "employeesMin", "label": "Registered employees from", "type": "number", "unit": "people"},
    {"key": "employeesMax", "label": "Registered employees to", "type": "number", "unit": "people"},
    {"key": "foundedAfter", "label": "Founded after (year)", "type": "number"},
    {"key": "revenueMin", "label": "Revenue from (researched companies reporting in NOK)", "type": "number", "unit": "NOK"},
    {"key": "revenueMax", "label": "Revenue to (researched companies reporting in NOK)", "type": "number", "unit": "NOK"},
    {"key": "hiring", "label": "Hiring now (researched companies)", "type": "boolean"},
]


def _money(num: str, unit: str | None) -> float:
    value = float(num.replace(",", ".").replace(" ", ""))
    u = (unit or "").lower()
    if u.startswith(("b", "mrd", "milliard")):
        return value * 1e9
    if u.startswith(("m", "mill")):
        return value * 1e6
    if u.startswith(("k", "tusen")):
        return value * 1e3
    return value


def _display(key: str, value: Any) -> str:
    if key in ("revenueMin", "revenueMax"):
        v = float(value)
        return f"NOK {v / 1e9:.1f}B" if v >= 1e9 else f"NOK {v / 1e6:.0f}M" if v >= 1e6 else f"NOK {v:,.0f}"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if key == "status":
        return {"active": "Active", "bankruptcy": "Bankruptcy", "under_liquidation": "Under liquidation"}.get(str(value), str(value))
    return str(value)


def interpret_text(text: str) -> dict[str, Any]:
    """Deterministic interpretation; returns QueryInterpretation."""
    original = text
    t = " " + text.casefold() + " "
    filters: dict[str, Any] = {}
    notes: list[str] = []
    m = re.search(r"(\d[\d\s]*)\s*\+?\s*(?:or more |eller flere )?(?:employees|ansatte|people|personer)", t)
    if m and re.search(r"(over|more than|mer enn|flere enn|minst|at least|\+)", t[max(0, m.start() - 14): m.end()]) or (m and "+" in m.group(0)):
        filters["employeesMin"] = int(m.group(1).replace(" ", ""))
    m2 = re.search(r"(?:under|less than|fewer than|færre enn|mindre enn|maks|max(?:imum)?)\s*(\d[\d\s]*)\s*(?:employees|ansatte|people)", t)
    if m2:
        filters["employeesMax"] = int(m2.group(1).replace(" ", ""))
    m3 = re.search(r"(\d[\d\s]*)\s*[-–]\s*(\d[\d\s]*)\s*(?:employees|ansatte)", t)
    if m3:
        filters["employeesMin"], filters["employeesMax"] = int(m3.group(1).replace(" ", "")), int(m3.group(2).replace(" ", ""))
    m4 = re.search(r"(?:founded|stiftet|established|etablert)\s*(?:after|since|etter|fra)\s*(\d{4})", t)
    if m4:
        filters["foundedAfter"] = int(m4.group(1))
    m5 = re.search(r"(?:revenue|omsetning|turnover)\s*(?:over|above|more than|mer enn|>)\s*(?:nok\s*)?(\d+(?:[.,]\d+)?)\s*(b\w*|m\w*|k\w*|mrd)?", t)
    if m5:
        filters["revenueMin"] = _money(m5.group(1), m5.group(2))
    m6 = re.search(r"(?:revenue|omsetning|turnover)\s*(?:under|below|less than|mindre enn|<)\s*(?:nok\s*)?(\d+(?:[.,]\d+)?)\s*(b\w*|m\w*|k\w*|mrd)?", t)
    if m6:
        filters["revenueMax"] = _money(m6.group(1), m6.group(2))
    if re.search(r"\b(hiring|recruiting|ansetter|rekrutterer|ledige stillinger)\b", t):
        filters["hiring"] = True
    if re.search(r"\b(bankrupt|konkurs)\b", t):
        filters["status"] = "bankruptcy"
    elif re.search(r"\b(liquidation|avvikling)\b", t):
        filters["status"] = "under_liquidation"
    elif re.search(r"\b(active|aktive?)\b", t):
        filters["status"] = "active"
    for name in sorted(list(MUNICIPALITIES) + list(COUNTY_NAMES), key=len, reverse=True):
        if re.search(rf"(?<![\wæøå]){re.escape(name)}(?![\wæøå])", t):
            filters["municipality"] = title_case_no(name.upper())
            break
    for words, _code, label in INDUSTRY_WORDS:
        if any(re.search(rf"(?<![\wæøå]){re.escape(w)}", t) for w in words):
            filters["industry"] = label
            break
    code = re.search(r"\b(\d{2}(?:\.\d{1,3})?)\b(?=.*(nace|næringskode|industry code))", t)
    if code:
        filters["industry"] = code.group(1)
    used = set()
    for value in filters.values():
        used.update(re.findall(r"[\wæøå]+", str(value).casefold()))
    tokens = [w for w in re.findall(r"[\wæøå&.-]+", original) if w.casefold() not in STOP_WORDS and w.casefold() not in used and not re.fullmatch(r"[\d.,+]+", w)]
    industry_words = {w for words, _c, _l in INDUSTRY_WORDS for w in words}
    tokens = [w for w in tokens if w.casefold() not in industry_words and fold(w) not in MUNICIPALITIES and fold(w) not in COUNTY_NAMES]
    keywords = " ".join(tokens).strip() or None
    if any(k in filters for k in ("revenueMin", "revenueMax", "hiring")):
        notes.append("Revenue and hiring filters apply to companies COGNIS has already researched.")
    return {"original": original, "filters": [{"key": k, "label": LABELS[k], "value": v, "display": _display(k, v)} for k, v in filters.items()],
            **({"keywords": keywords} if keywords else {}), **({"notes": notes} if notes else {})}


async def interpret(s: Any, text: str) -> dict[str, Any]:
    result = interpret_text(text)
    if s.provider is not None and len(text.split()) >= 3:
        runner = s.runner()
        llm = await llm_tasks.interpret_with_llm(runner, text, ALLOWED_KEYS)
        if llm:
            have = {f["key"] for f in result["filters"]}
            for f in llm[0]:
                if f["key"] not in have:
                    result["filters"].append({"key": f["key"], "label": LABELS.get(f["key"], f["key"]), "value": f["value"], "display": _display(f["key"], f["value"])})
    return result


async def municipality_numbers(s: Any, place: str) -> list[str]:
    key = fold(place)
    if key in MUNICIPALITIES:
        return [MUNICIPALITIES[key]]
    table = await _geonorge_municipalities(s)
    if key in COUNTY_NAMES:
        prefix = COUNTY_NAMES[key]
        return sorted(num for num in table.values() if num.startswith(prefix))[:60]
    if key in table:
        return [table[key]]
    if re.fullmatch(r"\d{4}", place.strip()):
        return [place.strip()]
    return []


async def _geonorge_municipalities(s: Any) -> dict[str, str]:
    cached = s.kv_get("geonorge-municipalities")
    if cached:
        return cached
    res = await s.ctx().fetch("https://ws.geonorge.no/kommuneinfo/v1/kommuner", connector="geonorge", accept="application/json", expect="json",
                              cache_ttl=30 * 24 * 3600, optional=True)
    table: dict[str, str] = {}
    if res.ok:
        for row in res.json() or []:
            num = str(row.get("kommunenummer") or "")
            for name in (row.get("kommunenavnNorsk"), row.get("kommunenavn")):
                if name and num:
                    table[fold(str(name))] = num
    if table:
        s.kv_set("geonorge-municipalities", table)
    return table


def industry_code(value: str) -> str | None:
    v = fold(value)
    if re.fullmatch(r"\d{2}(\.\d{1,3})?", v):
        return v
    for words, code, label in INDUSTRY_WORDS:
        if v == fold(label) or any(fold(w) == v or fold(w) in v for w in words):
            return code
    return None


async def discover(s: Any, body: dict[str, Any]) -> dict[str, Any]:
    filters: dict[str, Any] = dict(body.get("filters") or {})
    text = (body.get("text") or "").strip()
    page = max(1, int(body.get("page") or 1))
    page_size = max(1, min(int(body.get("pageSize") or 20), 100))
    interpretation = None
    keywords = None
    if text and body.get("interpret"):
        interpretation = await interpret(s, text)
        for f in interpretation["filters"]:
            filters.setdefault(f["key"], f["value"])
        keywords = interpretation.get("keywords")
    elif text:
        keywords = text
    params: dict[str, Any] = {"size": page_size, "page": page - 1}
    notes: list[str] = []
    if keywords:
        params["navn"] = keywords
    place = filters.get("municipality") or filters.get("location")
    if place:
        nums = await municipality_numbers(s, str(place))
        if nums:
            params["kommunenummer"] = ",".join(nums)
        else:
            notes.append(f"“{place}” was not recognised as a Norwegian municipality or county, so no location filter was applied.")
    if filters.get("industry"):
        code = industry_code(str(filters["industry"]))
        if code:
            params["naeringskode"] = code
        else:
            notes.append(f"No industry code matched “{filters['industry']}”.")
    if filters.get("employeesMin") is not None:
        params["fraAntallAnsatte"] = int(filters["employeesMin"])
    if filters.get("employeesMax") is not None:
        params["tilAntallAnsatte"] = int(filters["employeesMax"])
    if filters.get("foundedAfter"):
        params["fraStiftelsesdato"] = f"{int(filters['foundedAfter'])}-01-01"
    status = filters.get("status")
    if status == "bankruptcy":
        params["konkurs"] = "true"
    elif status == "under_liquidation":
        params["underAvvikling"] = "true"
    elif status == "active":
        params["konkurs"] = "false"
        params["underAvvikling"] = "false"
    research_filters = any(filters.get(k) not in (None, "", False) for k in ("revenueMin", "revenueMax", "hiring", "coverageMin", "recentActivity"))
    if research_filters:
        items = _researched_matches(s, filters, keywords, notes)
        total = len(items)
        items = items[(page - 1) * page_size: page * page_size]
    else:
        rows, total = await s.search_entities(params)
        items = s.summaries_for_rows(rows)
    sort = body.get("sort") or "relevance"
    keyfn = {"name": lambda c: c["legalName"].casefold(), "employees": lambda c: -(c.get("employees") or -1),
             "revenue": _revenue_sort_key, "researched": lambda c: c.get("lastResearchedAt") or "",
             "hiring": lambda c: -(c.get("openPositions") or -1)}.get(sort)
    if keyfn:
        items.sort(key=keyfn, reverse=sort == "researched")
    if interpretation is not None and notes:
        interpretation.setdefault("notes", []).extend(notes)
    out = {"items": items, "total": int(total), "page": page, "pageSize": page_size, "appliedFilters": {k: v for k, v in filters.items() if v not in (None, "")}}
    if interpretation is not None:
        out["interpretation"] = interpretation
    return out


def _revenue_sort_key(company: dict[str, Any]) -> tuple[int, str, float]:
    """Largest first *within one currency*: amounts in different currencies are never ranked against each other (no conversion)."""
    rev = company.get("revenue") or {}
    if rev.get("value") is None:
        return (2, "", 0.0)
    cur = rev.get("currency") or ""
    return (0 if cur == "NOK" else 1, cur, -float(rev["value"]))


def _researched_matches(s: Any, filters: dict[str, Any], keywords: str | None, notes: list[str] | None = None) -> list[dict[str, Any]]:
    out = []
    other_currency = 0
    for row in s.db.all("SELECT org_number FROM companies WHERE research_state = 'researched'"):
        record = repo.latest_record(s.db, row["org_number"])
        if record is None:
            continue
        c = s.profile_for(record)["company"]
        rev = (c.get("revenue") or {}).get("value")
        if filters.get("revenueMin") is not None or filters.get("revenueMax") is not None:
            # The thresholds are NOK. A filing in another currency (or with none stated) is never compared against them: that would need an
            # exchange rate this backend does not have, and treating 67 960 000 000 USD as NOK is exactly the error this guards against.
            if rev is not None and (c.get("revenue") or {}).get("currency") != "NOK":
                other_currency += 1
                continue
        if filters.get("revenueMin") is not None and (rev is None or rev < float(filters["revenueMin"])):
            continue
        if filters.get("revenueMax") is not None and (rev is None or rev > float(filters["revenueMax"])):
            continue
        if filters.get("hiring") and not c.get("openPositions"):
            continue
        if filters.get("coverageMin") is not None and c["coverage"]["complete"] < int(filters["coverageMin"]):
            continue
        if filters.get("municipality") and fold(str(filters["municipality"])) not in fold(c.get("municipality") or "") + " " + fold(c.get("county") or ""):
            continue
        if keywords and fold(keywords) not in fold(c["legalName"]):
            continue
        out.append(c)
    if other_currency and notes is not None:
        notes.append(f"{other_currency} researched {'company reports' if other_currency == 1 else 'companies report'} revenue in a currency other than NOK and "
                     "could not be matched against the NOK revenue filter (no currency conversion is applied).")
    return out


async def global_search(s: Any, q: str) -> dict[str, Any]:
    from .library import all_summaries

    query = q.strip()
    digits = re.sub(r"\D", "", query)
    companies: list[dict[str, Any]] = []
    intent: dict[str, Any] = {"kind": "mixed"}
    if len(digits) == 9 and len(re.sub(r"[\s.]", "", query)) == 9:
        try:
            org = s.clean_org(digits)
            record = await s.ensure_record(org)
            companies = [s.profile_for(record)["company"]]
            intent = {"kind": "company", "orgNumber": org}
        except Exception:
            companies = []
    elif len(query) >= 2:
        looks_like_criteria = bool(re.search(r"\b(in|i|with|med|over|under|employees|ansatte|hiring|companies|selskaper|founded)\b", query, re.I)) and len(query.split()) >= 3
        if looks_like_criteria:
            intent = {"kind": "discover", "text": query}
        try:
            rows, _ = await s.search_entities({"navn": query, "size": 8})
            companies = s.summaries_for_rows(rows)
        except Exception:
            companies = []
        exact = [c for c in companies if fold(c["legalName"]).removesuffix(" as") == fold(query).removesuffix(" as")]
        if len(exact) == 1 and not looks_like_criteria:
            intent = {"kind": "company", "orgNumber": exact[0]["orgNumber"]}
    needle = query.casefold()
    library = [a for a in all_summaries(s, include_archived=False) if needle and needle in (a["title"] + " " + (a.get("orgNumber") or "")).casefold()]
    return {"query": query, "intent": intent, "companies": companies,
            "artifacts": [a for a in library if a["type"] == "company"][:8],
            "sheets": [sh for sh in s.sheets.list() if needle and needle in sh["title"].casefold()][:5],
            "reports": [a for a in library if a["type"] == "report"][:5], "savedSearches": []}
