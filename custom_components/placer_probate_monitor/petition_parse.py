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
RESIDENCE_RE = re.compile(
    r"residence at time of\s*death\s*\(specify\):\s*(?P<body>.+?)"
    r"(?:Form Adopted|Fonn |Character and estimated value|3\.\s*d\.|PETITION FOR PROBATE)",
    re.I | re.S,
)
ROAD = (
    r"(?:Road|Rd|Lane|Ln|Drive|Dr|Street|St|Way|Court|Ct|Avenue|Ave|"
    r"Place|Pl|Circle|Cir|Boulevard|Blvd|Highway|Hwy)\.?"
)
ADDR_PATTERNS = [
    re.compile(
        rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+\s+{ROAD})"
        rf"\s+(?P<city>[A-Za-z][A-Za-z .'-]+?),\s*"
        rf"(?P<state>CA|WA|OR|NV|AZ|ID)\s*(?P<zip>\d{{5}}(?:-\d{{4}})?)?",
        re.I,
    ),
    re.compile(
        rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+\s+{ROAD})"
        rf"\s+(?P<city>[A-Za-z][A-Za-z .'-]+?)"
        rf"\s+(?:Placer(?:\s+County)?\s+)?(?P<state>CA|WA|OR|NV)\s+"
        rf"(?P<zip>\d{{5}}(?:-\d{{4}})?)(?:\s*\(Placer County\))?",
        re.I,
    ),
    re.compile(
        rf"(?P<street>\d{{1,6}}(?:\s+[A-Za-z0-9.'#\-]+)+\s+{ROAD})"
        rf"\s+(?P<city>[A-Za-z][A-Za-z .'-]+?)\s*,\s*Placer County",
        re.I,
    ),
    re.compile(
        r"(?P<street>\d{1,6}\s+[^\n]+?)\s+"
        r"(?P<city>[A-Za-z][A-Za-z .'-]+),\s*"
        r"(?P<state>CA|WA|OR|NV|AZ|ID)\s*(?P<zip>\d{5}(?:-\d{4})?)?",
        re.I,
    ),
]
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
    return "\n".join(parts)


def _parse_address(body: str) -> dict:
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(
        r",\s+(Road|Rd\.?|Lane|Ln\.?|Drive|Dr\.?|Street|St\.?|Way|Court|Ct\.?|"
        r"Avenue|Ave\.?|Place|Pl\.?|Circle|Cir\.?)\b",
        r" \1",
        body,
        flags=re.I,
    )
    for pattern in ADDR_PATTERNS:
        addr = pattern.search(body)
        if not addr:
            continue
        street = re.sub(r"\s+", " ", addr.group("street")).strip(" ,.")
        city = addr.group("city").strip(" ,.")
        if city.lower() in {"road", "street", "lane", "drive", "way", "court"}:
            continue
        state = (addr.groupdict().get("state") or "CA").upper()
        zipp = addr.groupdict().get("zip") or ""
        line = f"{street}, {city}"
        if state:
            line += f", {state}"
        if zipp:
            line += f" {zipp}"
        return {
            "decedent_residence": line,
            "decedent_city": city,
            "decedent_zip": zipp,
        }
    return {}


def parse_de111_text(text: str) -> dict:
    text = _clean(text)
    out: dict = {}
    died = DIED_RE.search(text)
    if died:
        out["decedent_died"] = died.group("date").strip()
        out["death_place"] = re.sub(r"\s+", " ", died.group("place")).strip(" .")
    if RESIDENT_RE.search(text) and not re.search(
        r"\[\s*[xX]\s*[_\]]\s*[^.\n]{0,40}nonresident of California", text
    ):
        out["county_resident"] = True
    res = RESIDENCE_RE.search(text)
    if res:
        out.update(_parse_address(res.group("body")))
    personal = PERSONAL_RE.search(text)
    if personal:
        out["estate_personal"] = personal.group("amt").replace(",", "")
    real = REAL_RE.search(text)
    if real:
        out["estate_real"] = real.group("amt").replace(",", "")
    return out


def parse_de111_pdf(path: Path) -> dict:
    return parse_de111_text(extract_pdf_text(path))


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
