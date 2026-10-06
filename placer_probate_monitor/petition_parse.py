"""Parse California DE-111 Petition for Probate text (pypdf extract)."""

from __future__ import annotations

import re
from pathlib import Path

DIED_RE = re.compile(
    r"Decedent died on \(date\):\s*(?P<date>"
    r"\d{1,2}/\d{1,2}/\d{2,4}|[A-Za-z]+ \d{1,2}, \d{4})"
    r"\s+at \(place\):\s*(?P<place>.+?)(?:\s*\(\s*1\s*\)|\s*a resident|\s*\[\s*_)",
    re.I | re.S,
)
RESIDENT_RE = re.compile(r"\(\s*1\s*\)\s*a resident of the county named above", re.I)
NONRESIDENT_RE = re.compile(
    r"a nonresident of California and left an estate in the county named above",
    re.I,
)
ITEM3A2_RE = re.compile(
    r"\(\s*2\s*\)\s*(?P<mark>.{0,16}?)\s*a\s*nonresident of California and left an estate"
    r".*?located at(?:\s*\([^)]{0,160}\))?\s*:?\s*(?P<body>.+?)"
    r"(?=\n\s*b\.|\n\s*c\.|Street address, city, and county of|"
    r"Decedent was a citizen|Form Adopted)",
    re.I | re.S,
)
ITEM3B_RE = re.compile(
    r"citizen of a country other than the United States\s*\(specify country\):\s*"
    r"(?P<country>[A-Za-z][A-Za-z .'-]{1,80})?",
    re.I,
)
RESIDENCE_RE = re.compile(
    r"(?:c\.\s*)?(?:Street address,\s*city,\s*and\s*county of\s+)?"
    r"decedent'?s?\s+residence at time of\s*death\s*\(specify\):\s*(?P<body>.+?)"
    r"(?:Form Adopted|Fonn |Character and estimated value|3\.\s*d\.|"
    r"4\.\s|Publication of Notice|PETITION FOR PROBATE)",
    re.I | re.S,
)
US_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
STATE_ALIAS = {}
for _code, _name in US_STATE_NAMES.items():
    STATE_ALIAS[_code.lower()] = _code
    STATE_ALIAS[_name.lower()] = _code
STATE_ALT = "|".join(
    sorted(US_STATE_NAMES.values(), key=len, reverse=True)
    + sorted(US_STATE_NAMES.keys(), key=len, reverse=True)
)
# Require a word break so FL/PA/OR do not match Flathead/Placer/Oregon.
ROAD = (
    r"(?:County\s+Rout[e]?|Route|Rte|Rout|"
    r"Road|Rd|Lane|Ln|Drive|Dr|Street|St|Way|Court|Ct|Avenue|Ave|"
    r"Place|Pl|Circle|Cir|Boulevard|Blvd|Highway|Hwy)\.?"
)
UNIT = r"(?:\s*,?\s*(?:Suite|Ste\.?|Unit|Apt\.?|#)\s*[A-Z0-9\-]+)"
_ADDR_TAIL = (
    rf"(?P<city>(?!Placer(?:\s+County)?\b)[A-Za-z][A-Za-z .'-]+?)\s*,\s*"
    rf"(?:(?P<county>[A-Za-z][A-Za-z .'-]+?)\s+County\s*,\s*)?"
    rf"(?P<state>{STATE_ALT})\b\.?\s*"
    rf"(?P<zip>\d{{5}}(?:-\d{{4}})?)?"
)
ITEM3C_ADDR_RE = re.compile(
    rf"(?P<street>\d{{1,6}}\s+(?!\d+\s)(?:[A-Za-z0-9.'#\-]+\s+)*{ROAD}{UNIT}?)\s*,\s*"
    rf"{_ADDR_TAIL}",
    re.I,
)
US_LINE_RE = re.compile(
    rf"(?P<street>\d{{1,6}}\s+(?!\d+\s)[^,\n]{{2,60}}?)\s*,\s*"
    rf"{_ADDR_TAIL}",
    re.I,
)
PHONE_RE = re.compile(
    r"(?:Telephone(?:\s+no\.?)?|Phone(?:\s+no\.?)?|Tel\.?)\s*:?\s*"
    r"(?P<phone>\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})",
    re.I,
)
EMAIL_RE = re.compile(
    r"(?:E-?mail(?:\s+address)?\s*:?\s*)?"
    r"(?P<email>[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})",
    re.I,
)
PETITIONER_ITEM_RE = re.compile(
    r"(?:1|2)\.?\s*Petitioner\s*(?:\([^)]*name[^)]*\))?\s*:?\s*(?P<body>.+?)"
    r"(?=requests that|2\.\s*Petitioner\s+is\b|2\.\s*[a-d]\.|3\.\s*Decedent|"
    r"Publication of Notice|Character and estimated value)",
    re.I | re.S,
)
ITEM2_NAMES_RE = re.compile(
    r"Petitioner\s*\(name each\)\s*:?\s*(?P<names>.+?)\s*requests that",
    re.I | re.S,
)
ITEM8_RE = re.compile(
    r"8\.\s*Name and relationship to decedent(?P<header>.{0,500}?)Address(?P<body>.+?)"
    r"(?:Continued on Attachment 8|Number of pages attached|"
    r"I declare under penalty|TYPE OR PRINT NAME)",
    re.I | re.S,
)
ITEM3H_RE = re.compile(
    r"nonresident of California\s*\(specify permanent address\):\s*(?P<body>.{0,400}?)"
    r"(?=resident of the United|nonresident of the United|4\.\s|8\.\s|DE-111|Form Adopted)",
    re.I | re.S,
)
PERMANENT_ADDR_RE = re.compile(
    r"permanent address\)\s*:\s*(?P<body>.{0,200})",
    re.I | re.S,
)
CAPTION_ADDR_RE = re.compile(
    r"STREET ADDRESS:\s*(?P<street>[^\n]+?)\s+"
    r"CITY:\s*(?P<city>[A-Za-z .'-]+)\s+"
    r"STATE:\s*(?P<state>[A-Z]{2})\s+"
    r"ZIP(?:\s*CODE)?:\s*(?P<zip>\d{5}(?:-\d{4})?)",
    re.I,
)
IN_PRO_PER_RE = re.compile(
    r"ATTORNEY FOR \(name\):\s*(?P<who>[^\n]{0,80})",
    re.I,
)
ADDR_PATTERNS = [
    re.compile(
        rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+\s+{ROAD}{UNIT}?)"
        rf"\s*,?\s*(?P<city>[A-Za-z][A-Za-z .'-]+?)\s*,\s*Placer County",
        re.I,
    ),
    re.compile(
        rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+\s+{ROAD}{UNIT}?)"
        rf"\s*,?\s*(?P<city>[A-Za-z][A-Za-z .'-]+?),\s*"
        rf"(?P<state>{STATE_ALT})\b\s*(?P<zip>\d{{5}}(?:-\d{{4}})?)?",
        re.I,
    ),
    re.compile(
        rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+\s+{ROAD}{UNIT}?)"
        rf"\s+(?P<city>[A-Za-z][A-Za-z .'-]+?)"
        rf"\s+(?:Placer(?:\s+County)?\s+)?(?P<state>{STATE_ALT})\b\s+"
        rf"(?P<zip>\d{{5}}(?:-\d{{4}})?)(?:\s*\(Placer County\))?",
        re.I,
    ),
    re.compile(
        rf"(?P<street>\d{{1,6}}\s+[^\n]+?{ROAD}{UNIT}?)\s+"
        r"(?P<city>[A-Za-z][A-Za-z .'-]+),\s*"
        rf"(?P<state>{STATE_ALT})\b\s*(?P<zip>\d{{5}}(?:-\d{{4}})?)?",
        re.I,
    ),
]
COUNTY_NOISE_RE = re.compile(r",?\s*Placer(?:\s+County)?\b,?", re.I)
NOT_CITIES = {"placer", "placer county", "county", "california"}


def _strip_county_noise(text: str) -> str:
    text = COUNTY_NOISE_RE.sub(",", text)
    text = re.sub(r"\s*,\s*,+", ",", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def _usable_city(city: str) -> str:
    low = re.sub(r"\s+", " ", (city or "").strip().lower())
    if not low or low in NOT_CITIES or low.endswith(" county"):
        return ""
    return (city or "").strip()


def _state_code(raw: str) -> str:
    key = re.sub(r"\s+", " ", (raw or "").strip().lower())
    if key in STATE_ALIAS:
        return STATE_ALIAS[key]
    return (raw or "").strip().upper()[:2]


def split_de111_address(line: str) -> dict:
    """Parse DE-111 §3c lines like '1728 6th Street, Lincoln, Placer County, California 95648'."""
    text = re.sub(r"[ \t]+", " ", (line or "").replace("\n", " ")).strip(" .")
    text = re.sub(r"\s+,", ",", text)
    if not text:
        return {}
    match = ITEM3C_ADDR_RE.search(text) or US_LINE_RE.search(text)
    if not match:
        stripped = _strip_county_noise(text)
        match = ITEM3C_ADDR_RE.search(stripped) or US_LINE_RE.search(stripped)
    if not match:
        return {}
    city = _usable_city(match.group("city"))
    street = re.sub(r"\s+", " ", match.group("street")).strip(" ,.")
    if not street or not city:
        return {}
    return {
        "street": street,
        "city": city,
        "county": re.sub(r"\s+", " ", (match.group("county") or "")).strip(),
        "state": _state_code(match.group("state")),
        "zip": (match.group("zip") or "").strip(),
    }


PERSONAL_RE = re.compile(r"Personal property:\s*\$?\s*(?P<amt>[0-9,]+(?:\.\d{2})?)", re.I)
REAL_RE = re.compile(
    r"Gross fair market value of real property:\s*\$?\s*(?P<amt>[0-9,]+(?:\.\d{2})?)",
    re.I,
)


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u2019", "'")
    return re.sub(r"[ \t]+", " ", text)


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    page_text = "\n".join(parts)
    field_lines: list[str] = []
    try:
        fields = reader.get_fields() or {}
    except Exception:  # noqa: BLE001
        fields = {}
    for key, field in fields.items():
        value = _field_value(field) if isinstance(field, dict) else ""
        if not value:
            continue
        field_lines.append(f"{key}: {value}")
    if not field_lines:
        return page_text
    blob = "\n".join(field_lines)
    marker = re.search(r"8\.\s*Name and relationship to decedent", page_text, re.I)
    if marker:
        at = marker.end()
        return page_text[:at] + "\n" + blob + "\n" + page_text[at:]
    return (
        page_text
        + "\n8. Name and relationship to decedent Age Address\n"
        + blob
        + "\nI declare under penalty\n"
    )


def _address_from_groups(street: str, city: str, state: str, zipp: str, *, prefix: str) -> dict:
    street = re.sub(r"\s+", " ", street).strip(" ,.")
    city = _usable_city(city)
    if not street or not city or city.lower() in {"road", "street", "lane", "drive", "way", "court"}:
        return {}
    state = _state_code(state or "CA") or "CA"
    zipp = zipp or ""
    line = f"{street}, {city}"
    if state:
        line += f", {state}"
    if zipp:
        line += f" {zipp}"
    if prefix == "mailing":
        return {
            "mailing_address": line,
            "mailing_city": city,
            "mailing_state": state,
            "mailing_zip": zipp,
        }
    return {
        "decedent_residence": line,
        "decedent_city": city,
        "decedent_state": state,
        "decedent_zip": zipp,
    }


def _parse_address(body: str, *, prefix: str = "decedent") -> dict:
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(
        r",\s+(Road|Rd\.?|Lane|Ln\.?|Drive|Dr\.?|Street|St\.?|Way|Court|Ct\.?|"
        r"Avenue|Ave\.?|Place|Pl\.?|Circle|Cir\.?)\b",
        r" \1",
        body,
        flags=re.I,
    )
    split = split_de111_address(body)
    if split:
        return _address_from_groups(
            split["street"],
            split["city"],
            split.get("state") or "CA",
            split.get("zip") or "",
            prefix=prefix,
        )
    stripped = _strip_county_noise(body)
    for pattern in ADDR_PATTERNS:
        addr = pattern.search(stripped)
        if not addr:
            continue
        parsed = _address_from_groups(
            addr.group("street"),
            addr.group("city"),
            addr.groupdict().get("state") or "CA",
            addr.groupdict().get("zip") or "",
            prefix=prefix,
        )
        if parsed:
            return parsed
    return {}


def _parse_caption_mailing(text: str) -> dict:
    who = ""
    listed = IN_PRO_PER_RE.search(text)
    if listed:
        who = listed.group("who").strip().lower()
    in_pro_per = any(
        token in who
        for token in ("pro per", "propria", "self-represented", "in pro per")
    )
    if not in_pro_per:
        return {}
    cap = CAPTION_ADDR_RE.search(text)
    if not cap:
        return {}
    return _address_from_groups(
        cap.group("street"),
        cap.group("city"),
        cap.group("state"),
        cap.group("zip") or "",
        prefix="mailing",
    )


def _item1_body(text: str) -> str:
    pet = PETITIONER_ITEM_RE.search(text)
    if pet:
        return pet.group("body")
    fallback = re.search(
        r"(?:1|2)\.?\s*Petitioner\b(.{0,3000}?)(?:\n\s*2\.|\n\s*3\.\s*Decedent|requests that)",
        text,
        re.I | re.S,
    )
    return fallback.group(1) if fallback else ""


def _name_tokens(name: str) -> set[str]:
    skip = {
        "the",
        "estate",
        "of",
        "decedent",
        "petitioner",
        "and",
        "aka",
        "a/k/a",
        "jr",
        "sr",
        "ii",
        "iii",
    }
    return {
        part.lower()
        for part in re.findall(r"[A-Za-z']{2,}", name or "")
        if part.lower() not in skip
    }


def _item2_names(text: str) -> str:
    match = ITEM2_NAMES_RE.search(text)
    if not match:
        return ""
    names = re.sub(r"\s+", " ", match.group("names")).strip(" :.")
    if len(names) > 200:
        return names[:200]
    return names


def _estate_of_name(text: str) -> str:
    match = re.search(
        r"ESTATE\s+OF\s*\(\s*name\s*\)\s*:?\s*(?P<name>[^\n]{3,90})",
        text or "",
        re.I,
    )
    if not match:
        return ""
    name = re.sub(r"\s+", " ", match.group("name")).strip(" :.")
    name = re.split(r"\bAKA\b", name, maxsplit=1, flags=re.I)[0].strip(" :.")
    if len(name) < 3 or re.search(r"\d{3,}", name):
        return ""
    return name


def _first_parsed_address(body: str, *, prefix: str) -> dict:
    split = split_de111_address(body)
    if split:
        return _address_from_groups(
            split["street"],
            split["city"],
            split.get("state") or "CA",
            split.get("zip") or "",
            prefix=prefix,
        )
    return _parse_address(body, prefix=prefix)


def _parsed_from_addr_match(hit: re.Match, *, prefix: str) -> dict:
    return _address_from_groups(
        hit.group("street"),
        hit.group("city"),
        hit.group("state"),
        hit.group("zip") or "",
        prefix=prefix,
    )


def _iter_us_addresses(blob: str, *, prefix: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    search_from = 0
    while True:
        hit = ITEM3C_ADDR_RE.search(blob, search_from) or US_LINE_RE.search(blob, search_from)
        if not hit:
            break
        search_from = hit.end()
        parsed = _parsed_from_addr_match(hit, prefix=prefix)
        key = str(parsed.get("mailing_address") or parsed.get("decedent_residence") or "")
        if not parsed or key in seen:
            continue
        seen.add(key)
        found.append(parsed)
    return found


def _item8_people(header: str) -> list[str]:
    people: list[str] = []
    for raw in (header or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" .")
        if not line:
            continue
        low = line.lower()
        if any(
            bit in low
            for bit in ("age", "adult", "minor", "relationship", "decedent", "name and", "address")
        ):
            continue
        if re.search(r"\d{5}", line) or re.match(r"\d", line):
            continue
        if len(_name_tokens(line)) >= 2:
            people.append(line)
    return people


def _item8_petitioner_address(text: str, petitioner_name: str = "") -> dict:
    match = ITEM8_RE.search(text)
    if not match:
        return {}
    header = match.group("header") or ""
    body = match.group("body") or ""
    addrs = _iter_us_addresses(body, prefix="mailing")
    if not addrs:
        return {}
    tokens = _name_tokens(petitioner_name)
    people = _item8_people(header)
    if tokens and people:
        for idx, person in enumerate(people):
            overlap = tokens & _name_tokens(person)
            first = (petitioner_name.split() or [""])[0].lower()
            if first and len(first) > 2 and first not in _name_tokens(person):
                continue
            if overlap and idx < len(addrs):
                return addrs[idx]
        if tokens & _name_tokens(header) and addrs:
            return addrs[0]
        return {}
    return addrs[0]


def _item3h_address(text: str) -> dict:
    match = ITEM3H_RE.search(text) or PERMANENT_ADDR_RE.search(text)
    if not match:
        return {}
    return _contact_from_blob(match.group("body")[:500])


def _checkbox_marked(mark: str) -> bool:
    blob = re.sub(r"\s+", "", mark or "")
    if not blob or re.fullmatch(r"[\[\]Il1|_-]+", blob):
        return False
    return bool(
        re.search(
            r"[xX✓✔☒☑√×✗■●▪◼◆•*]|\ufffd|\u25a0|\u2713|\u2714|\u2611",
            blob,
        )
    )


def _looks_like_place_of_death(line: str, death_place: str = "") -> bool:
    """True when a value is item 3 'at (place)', not a street in 3.a.(2) or 3c."""
    text = re.sub(r"\s+", " ", (line or "")).strip().lower()
    if not text:
        return False
    if not re.search(r"\d{1,6}\s+\S+", text):
        return True
    place = re.sub(r"\s+", " ", (death_place or "")).strip().lower()
    return bool(place and text == place)


def _item3a2_estate_address(text: str) -> dict:
    bodies: list[str] = []
    match = ITEM3A2_RE.search(text or "")
    marked = bool(match and _checkbox_marked(match.group("mark") or ""))
    if match:
        bodies.append(match.group("body") or "")
    fallback = re.search(
        r"left an estate in the county named above.{0,240}?located at"
        r"(?:\s*\([^)]{0,200}\))?\s*:?\s*(?P<body>.+?)"
        r"(?=c\.?\s*Street address|Street address, city, and county of|"
        r"decedent'?s?\s+residence at time of death|Form Adopted)",
        text or "",
        re.I | re.S,
    )
    if fallback:
        bodies.append(fallback.group("body") or "")
    parsed: dict = {}
    for body in bodies:
        parsed = _parse_address(body[:400], prefix="decedent")
        if parsed.get("decedent_residence"):
            break
    if marked or parsed.get("decedent_residence"):
        return parsed
    return {}


def parse_de111_text(text: str, petitioner_name: str = "") -> dict:
    text = _clean(text)
    out: dict = {}
    died = DIED_RE.search(text)
    if died:
        out["decedent_died"] = died.group("date").strip()
        out["death_place"] = re.sub(r"\s+", " ", died.group("place")).strip(" .")
    item3a2 = _item3a2_estate_address(text)
    item3a2_box = ITEM3A2_RE.search(text)
    if item3a2 or (
        item3a2_box and _checkbox_marked(item3a2_box.group("mark") or "")
    ):
        out["county_resident"] = False
    elif NONRESIDENT_RE.search(text) and re.search(
        r"\[\s*[xX✓✔]\s*\][^\n]{0,80}nonresident of California", text
    ):
        out["county_resident"] = False
    elif RESIDENT_RE.search(text) or re.search(
        r"\[\s*[xX✓✔]\s*\][^\n]{0,80}a resident of the county named above", text
    ):
        out["county_resident"] = True
    citizen = ITEM3B_RE.search(text)
    if citizen:
        country = re.sub(r"\s+", " ", (citizen.group("country") or "")).strip(" .")
        if (
            country
            and country.lower() not in {"specify country", "street address"}
            and not re.match(r"^c\.?\s", country, re.I)
            and "street address" not in country.lower()
        ):
            out["decedent_citizenship"] = country
    if item3a2.get("decedent_residence") and not _looks_like_place_of_death(
        item3a2.get("decedent_residence") or "",
        out.get("death_place") or "",
    ):
        out.update(item3a2)
        out["decedent_address_source"] = "3a2"
    else:
        res = RESIDENCE_RE.search(text)
        if res:
            parsed_3c = _parse_address(res.group("body"))
            if parsed_3c.get("decedent_residence") and not _looks_like_place_of_death(
                parsed_3c.get("decedent_residence") or "",
                out.get("death_place") or "",
            ):
                out.update(parsed_3c)
                out["decedent_address_source"] = "3c"
        if not out.get("decedent_residence"):
            marker = re.search(
                r"residence at time of\s*death\s*\(specify\):",
                text,
                re.I,
            )
            if marker:
                parsed_3c = _parse_address(
                    text[marker.end() : marker.end() + 500], prefix="decedent"
                )
                if parsed_3c.get("decedent_residence") and not _looks_like_place_of_death(
                    parsed_3c.get("decedent_residence") or "",
                    out.get("death_place") or "",
                ):
                    out.update(parsed_3c)
                    out["decedent_address_source"] = "3c"
    if out.get("decedent_residence") and _looks_like_place_of_death(
        out.get("decedent_residence") or "",
        out.get("death_place") or "",
    ):
        for key in (
            "decedent_residence",
            "decedent_city",
            "decedent_state",
            "decedent_zip",
            "decedent_address_source",
        ):
            out.pop(key, None)
    body = _item1_body(text)
    names = _item2_names(text) or petitioner_name
    if names:
        out["petitioner_name"] = names
    estate = _estate_of_name(text)
    if estate:
        out["decedent_name"] = estate
    mailing = _item3h_address(text)
    if not mailing:
        mailing = _item8_petitioner_address(text, names)
    if not mailing and body:
        mailing = _parse_address(body, prefix="mailing")
        cap = CAPTION_ADDR_RE.search(text)
        cap_street = (cap.group("street").strip().lower() if cap else "")
        if (
            mailing
            and cap_street
            and cap_street in str(mailing.get("mailing_address") or "").lower()
            and not _parse_caption_mailing(text)
        ):
            mailing = {}
    out.update(mailing)
    skip_phones = _caption_phones(text)
    phone = _petitioner_phone_from_text(text, skip=skip_phones)
    if phone:
        out["petitioner_phone"] = phone
    if not out.get("petitioner_email"):
        email = EMAIL_RE.search(body) if body else None
        if email and _parse_caption_mailing(text):
            out["petitioner_email"] = email.group("email").strip()
    if not out.get("mailing_address"):
        out.update(_parse_caption_mailing(text))
    personal = PERSONAL_RE.search(text)
    if personal:
        out["estate_personal"] = personal.group("amt").replace(",", "")
    real = REAL_RE.search(text)
    if real:
        out["estate_real"] = real.group("amt").replace(",", "")
    return out


def _field_value(field) -> str:
    if not isinstance(field, dict):
        return ""
    value = field.get("/V")
    if value in (None, ""):
        return ""
    return str(value).strip()


def _mailing_from_form_fields(path: Path) -> dict:
    from pypdf import PdfReader

    try:
        fields = PdfReader(str(path)).get_fields() or {}
    except Exception:  # noqa: BLE001
        return {}
    blobs: list[str] = []
    for key, field in fields.items():
        name = str(key or "").lower()
        if any(bit in name for bit in ("atty", "attorney", "counsel", "firm")):
            continue
        if not any(
            bit in name
            for bit in (
                "petitioner",
                "partywithoutattorney",
                "inproper",
                "item1",
                "item2",
                "item8",
                "attachment8",
                "permanentaddress",
                "3h",
                "nameeach",
            )
        ):
            continue
        value = _field_value(field)
        if value:
            blobs.append(value)
    if not blobs:
        return {}
    return _parse_address("\n".join(blobs), prefix="mailing")


def _residence_from_form_fields(path: Path) -> dict:
    from pypdf import PdfReader

    try:
        fields = PdfReader(str(path)).get_fields() or {}
    except Exception:  # noqa: BLE001
        return {}
    blobs: list[str] = []
    for key, field in fields.items():
        name = str(key or "").lower()
        if any(bit in name for bit in ("atty", "attorney", "counsel", "firm", "petitioner")):
            continue
        if any(
            bit in name
            for bit in (
                "residence",
                "3c",
                "item3c",
                "decedentaddr",
                "decedent_addr",
                "lastaddress",
                "streetaddresscityandcounty",
            )
        ):
            value = _field_value(field)
            if value:
                blobs.append(value)
    if not blobs:
        return {}
    return _parse_address("\n".join(blobs), prefix="decedent")


def _pdf_field_pairs(path: Path) -> list[tuple[str, str]]:
    from pypdf import PdfReader

    try:
        fields = PdfReader(str(path)).get_fields() or {}
    except Exception:  # noqa: BLE001
        return []
    rows: list[tuple[str, str]] = []
    for key, field in fields.items():
        value = _field_value(field)
        if value:
            rows.append((str(key or ""), value))
    return rows


def _caption_street(text: str) -> str:
    cap = CAPTION_ADDR_RE.search(text or "")
    if not cap:
        return ""
    return re.sub(r"\s+", " ", cap.group("street")).strip().lower()


def _is_skip_address_field(name: str) -> bool:
    low = (name or "").lower()
    return any(
        bit in low
        for bit in (
            "atty",
            "attorney",
            "counsel",
            "firm",
            "lawyer",
            "court",
            "branch",
            "forcourtuse",
        )
    )


def _pick_mailing_from_fields(
    path: Path,
    petitioner_name: str,
    page_text: str,
) -> dict:
    pairs = _pdf_field_pairs(path)
    if not pairs:
        return {}
    tokens = _name_tokens(petitioner_name)
    first = (petitioner_name.split() or [""])[0].lower()
    attorney = _caption_street(page_text)
    best: tuple[int, dict] | None = None
    for idx, (name, value) in enumerate(pairs):
        if _is_skip_address_field(name):
            continue
        chunk = value
        if idx + 1 < len(pairs):
            chunk = f"{value}, {pairs[idx + 1][1]}"
        parsed = _first_parsed_address(value, prefix="mailing") or _first_parsed_address(
            chunk, prefix="mailing"
        )
        if not parsed:
            continue
        line = str(parsed.get("mailing_address") or "").lower()
        if attorney and attorney in line:
            continue
        if "101 maple" in line or "justice center" in line:
            continue
        neighbor = " ".join(
            pairs[j][1] for j in range(max(0, idx - 3), min(len(pairs), idx + 4))
        )
        window = f"{name} {neighbor}"
        window_tokens = _name_tokens(window)
        overlap = tokens & window_tokens if tokens else set()
        if first and len(first) > 2 and first not in window_tokens:
            continue
        score = len(overlap)
        low_name = name.lower()
        if any(bit in low_name for bit in ("item8", "att8", "heir", "interested")):
            score += 3
        if best is None or score > best[0]:
            best = (score, parsed)
    if not best:
        return {}
    if tokens and best[0] < 1:
        return {}
    return best[1]


def parse_de111_pdf(path: Path, petitioner: str = "") -> dict:
    text = extract_pdf_text(path)
    out = parse_de111_text(text, petitioner_name=petitioner)
    if not out.get("mailing_address"):
        out.update(_mailing_from_form_fields(path))
    if not out.get("mailing_address"):
        out.update(_pick_mailing_from_fields(path, petitioner or _item2_names(text), text))
    if out.get("decedent_address_source") != "3a2" and not out.get("decedent_residence"):
        extra = _residence_from_form_fields(path)
        if extra.get("decedent_residence") and not _looks_like_place_of_death(
            extra.get("decedent_residence") or "",
            out.get("death_place") or "",
        ):
            out.update(extra)
    return out


def looks_like_probate_petition(name: str) -> bool:
    low = (name or "").lower()
    compact = low.replace(" ", "").replace("-", "")
    if "de111" in compact:
        return True
    if "petition for probate" in low:
        return True
    if not low.startswith("petition"):
        return False
    return any(
        token in low
        for token in (
            "probate of will",
            "letters of administration",
            "letters testamentary",
            "petition for probate",
        )
    )


def looks_like_duties_form(name: str) -> bool:
    low = (name or "").lower()
    if "de-147" in low or "de147" in low:
        return True
    return "duties" in low and "personal representative" in low


DE147_CONTACT_RE = re.compile(
    r"My address and telephone number are\s*\(specify\)\s*:?\s*(?P<body>.+?)"
    r"(?:I acknowledge|acknowledge that|3\.\s|CONFIDENTIAL INFORMATION|Date:|pate:)",
    re.I | re.S,
)
BARE_PHONE_RE = re.compile(
    r"(?P<phone>\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})"
)
CAPTION_PHONE_RE = re.compile(
    r"TELEPHONE NO\.\s*:?\s*(?P<phone>\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})",
    re.I,
)
FAX_PHONE_RE = re.compile(
    r"FAX NO[^0-9]{0,24}(?P<phone>\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})",
    re.I,
)


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else digits


def _format_phone(raw: str) -> str:
    digits = _normalize_phone(raw)
    if len(digits) != 10:
        return re.sub(r"\s+", " ", (raw or "")).strip()
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _caption_phones(text: str) -> set[str]:
    found: set[str] = set()
    for rx in (CAPTION_PHONE_RE, FAX_PHONE_RE):
        for match in rx.finditer(text or ""):
            found.add(_normalize_phone(match.group("phone")))
    head = (text or "")[:1800]
    for match in BARE_PHONE_RE.finditer(head):
        if "attorney" in head.lower() or "telephone no" in head.lower():
            found.add(_normalize_phone(match.group("phone")))
    return {item for item in found if item}


def _contact_from_blob(body: str) -> dict:
    out: dict = {}
    blob = re.sub(r"\s+", " ", body or "").strip()
    phone = BARE_PHONE_RE.search(blob)
    rest = blob
    if phone:
        out["petitioner_phone"] = _format_phone(phone.group("phone"))
        rest = (blob[: phone.start()] + blob[phone.end() :]).strip()
    email = EMAIL_RE.search(rest)
    if email:
        out["petitioner_email"] = email.group("email").strip()
        rest = rest.replace(email.group("email"), " ")
    rest = re.sub(r"[\s;]+$", "", rest).strip(" ;,")
    parsed = _parse_address(rest, prefix="mailing") if rest else {}
    if parsed:
        out.update(parsed)
    return out


def _petitioner_phone_from_text(text: str, skip: set[str] | None = None) -> str:
    skip_n = set(skip or ())
    windows: list[str] = []
    for rx in (DE147_CONTACT_RE, ITEM3H_RE, ITEM8_RE, PERMANENT_ADDR_RE):
        match = rx.search(text or "")
        if match:
            windows.append(match.group(0))
    for label in (
        "ACKNOWLEDGMENT OF RECEIPT",
        "address and telephone number",
        "permanent address",
        "8. Name and relationship",
    ):
        idx = (text or "").lower().find(label.lower())
        if idx >= 0:
            windows.append(text[idx : idx + 800])
    for window in windows:
        for match in BARE_PHONE_RE.finditer(window):
            digits = _normalize_phone(match.group("phone"))
            if digits and digits not in skip_n:
                return _format_phone(match.group("phone"))
    return ""


CONTACT_KEYS = (
    "mailing_address",
    "mailing_city",
    "mailing_state",
    "mailing_zip",
    "petitioner_phone",
    "petitioner_email",
)


def contact_fields(data: dict | None) -> dict:
    out: dict = {}
    for key in CONTACT_KEYS:
        value = (data or {}).get(key)
        if value not in (None, "", [], {}):
            out[key] = value
    return out


def merge_petitioner_contact(*parts: dict) -> dict:
    """Use any petitioner address/phone/email found on DE-111, DE-147, or the row."""
    filled = [contact_fields(part) for part in parts]
    out: dict = {}
    for key in ("mailing_address", "mailing_city", "mailing_state", "mailing_zip"):
        for part in filled:
            if key in part:
                out[key] = part[key]
                break
    for key in ("petitioner_phone", "petitioner_email"):
        for part in reversed(filled):
            if key in part:
                out[key] = part[key]
                break
    return out


def parse_de147_text(text: str) -> dict:
    text = _clean(text)
    out: dict = {}
    match = DE147_CONTACT_RE.search(text)
    if match:
        out.update(_contact_from_blob(match.group("body")))
    if not out.get("mailing_address"):
        idx = text.lower().find("address and telephone number")
        if idx >= 0:
            out.update(_contact_from_blob(text[idx : idx + 500]))
    skip = _caption_phones(text)
    phone = out.get("petitioner_phone") or ""
    if not phone or _normalize_phone(phone) in skip:
        out.pop("petitioner_phone", None)
        phone = _petitioner_phone_from_text(text, skip=skip)
        if phone:
            out["petitioner_phone"] = phone
    return out


def parse_de147_pdf(path: Path) -> dict:
    return parse_de147_text(extract_pdf_text(path))
