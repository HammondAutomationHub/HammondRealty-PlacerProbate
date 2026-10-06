"""Parse California DE-111 Petition for Probate text (pypdf extract)."""

from __future__ import annotations

import re
from pathlib import Path

DIED_RE = re.compile(
    r"Decedent died on \(date\):\s*(?P<date>\d{1,2}/\d{1,2}/\d{2,4})"
    r"\s+at \(place\):\s*(?P<place>.+?)(?:\s*\(\s*1\s*\)|\s*a resident|\s*\[\s*_)",
    re.I | re.S,
)
RESIDENT_RE = re.compile(r"\(\s*1\s*\)\s*a resident of the county named above", re.I)
NONRESIDENT_RE = re.compile(
    r"a nonresident of California and left an estate in the county named above",
    re.I,
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
STATE_ALT = (
    r"California|Washington|Oregon|Nevada|Arizona|Idaho|CA|WA|OR|NV|AZ|ID"
)
STATE_ALIAS = {
    "ca": "CA",
    "california": "CA",
    "wa": "WA",
    "washington": "WA",
    "or": "OR",
    "oregon": "OR",
    "nv": "NV",
    "nevada": "NV",
    "az": "AZ",
    "arizona": "AZ",
    "id": "ID",
    "idaho": "ID",
}
ITEM3C_ADDR_RE = re.compile(
    rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+)\s*,\s*"
    rf"(?P<city>(?!Placer(?:\s+County)?\b)[A-Za-z][A-Za-z .'-]+?)\s*,\s*"
    rf"(?:(?P<county>[A-Za-z][A-Za-z .'-]+?)\s+County\s*,\s*)?"
    rf"(?P<state>{STATE_ALT})\.?\s*"
    rf"(?P<zip>\d{{5}}(?:-\d{{4}})?)?",
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
ROAD = (
    r"(?:Road|Rd|Lane|Ln|Drive|Dr|Street|St|Way|Court|Ct|Avenue|Ave|"
    r"Place|Pl|Circle|Cir|Boulevard|Blvd|Highway|Hwy)\.?"
)
UNIT = r"(?:\s*,?\s*(?:Suite|Ste\.?|Unit|Apt\.?|#)\s*[A-Z0-9\-]+)"
PETITIONER_ITEM_RE = re.compile(
    r"1\.?\s*Petitioner\s*(?:\([^)]*name[^)]*\))?\s*:?\s*(?P<body>.+?)"
    r"(?=2\.?\s*Petitioner\s+is\b|2\.?\s*Jurisdiction|"
    r"3\.\s*Decedent|Publication of Notice|Character and estimated value)",
    re.I | re.S,
)
CAPTION_ADDR_RE = re.compile(
    r"STREET ADDRESS:\s*(?P<street>[^\n]+?)\s+"
    r"CITY:\s*(?P<city>[A-Za-z .'-]+)\s+"
    r"STATE:\s*(?P<state>CA|WA|OR|NV|AZ|ID)\s+"
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
        rf"(?P<state>CA|WA|OR|NV|AZ|ID)\s*(?P<zip>\d{{5}}(?:-\d{{4}})?)?",
        re.I,
    ),
    re.compile(
        rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+\s+{ROAD}{UNIT}?)"
        rf"\s+(?P<city>[A-Za-z][A-Za-z .'-]+?)"
        rf"\s+(?:Placer(?:\s+County)?\s+)?(?P<state>CA|WA|OR|NV)\s+"
        rf"(?P<zip>\d{{5}}(?:-\d{{4}})?)(?:\s*\(Placer County\))?",
        re.I,
    ),
    re.compile(
        rf"(?P<street>\d{{1,6}}\s+[^\n]+?{ROAD}{UNIT}?)\s+"
        r"(?P<city>[A-Za-z][A-Za-z .'-]+),\s*"
        r"(?P<state>CA|WA|OR|NV|AZ|ID)\s*(?P<zip>\d{5}(?:-\d{4})?)?",
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
    match = ITEM3C_ADDR_RE.search(text)
    if not match:
        stripped = _strip_county_noise(text)
        match = ITEM3C_ADDR_RE.search(stripped)
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
    text = text.replace("\xa0", " ").replace("\u2019", "'").replace("\ufffd", "")
    return re.sub(r"[ \t]+", " ", text)


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    try:
        fields = reader.get_fields() or {}
    except Exception:  # noqa: BLE001
        fields = {}
    for field in fields.values():
        if not isinstance(field, dict):
            continue
        value = field.get("/V")
        if value in (None, ""):
            continue
        parts.append(str(value))
    return "\n".join(parts)


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
        r"1\.?\s*Petitioner\b(.{0,3000}?)(?:\n\s*2\.|\n\s*3\.\s*Decedent)",
        text,
        re.I | re.S,
    )
    return fallback.group(1) if fallback else ""


def parse_de111_text(text: str) -> dict:
    text = _clean(text)
    out: dict = {}
    died = DIED_RE.search(text)
    if died:
        out["decedent_died"] = died.group("date").strip()
        out["death_place"] = re.sub(r"\s+", " ", died.group("place")).strip(" .")
    if NONRESIDENT_RE.search(text) and re.search(
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
        if country and country.lower() not in {"specify country", "street address"}:
            out["decedent_citizenship"] = country
    res = RESIDENCE_RE.search(text)
    if res:
        out.update(_parse_address(res.group("body")))
    if not out.get("decedent_residence"):
        marker = re.search(
            r"residence at time of\s*death\s*\(specify\):",
            text,
            re.I,
        )
        if marker:
            out.update(_parse_address(text[marker.end() : marker.end() + 500], prefix="decedent"))
    body = _item1_body(text)
    if body:
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
        phone = PHONE_RE.search(body)
        if phone:
            out["petitioner_phone"] = re.sub(r"\s+", " ", phone.group("phone")).strip()
        email = EMAIL_RE.search(body)
        if email:
            out["petitioner_email"] = email.group("email").strip()
    if not out.get("mailing_address"):
        out.update(_parse_caption_mailing(text))
    if not out.get("petitioner_phone"):
        phone = PHONE_RE.search(text[:4000])
        if phone and _parse_caption_mailing(text):
            out["petitioner_phone"] = re.sub(r"\s+", " ", phone.group("phone")).strip()
    if not out.get("petitioner_email"):
        email = EMAIL_RE.search(body or text[:4000])
        if email and (body or _parse_caption_mailing(text)):
            out["petitioner_email"] = email.group("email").strip()
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
            for bit in ("petitioner", "partywithoutattorney", "inproper", "item1")
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


def parse_de111_pdf(path: Path) -> dict:
    out = parse_de111_text(extract_pdf_text(path))
    if not out.get("mailing_address"):
        out.update(_mailing_from_form_fields(path))
    if not out.get("decedent_residence"):
        out.update(_residence_from_form_fields(path))
    return out


def looks_like_probate_petition(name: str) -> bool:
    low = (name or "").lower()
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
