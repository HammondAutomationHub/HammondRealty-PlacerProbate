#!/usr/bin/env python3
"""Placer eCourt Public lookups. Requires a search-then-open session."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PORTAL_SEARCH = "https://webportal.placerco.org/eCourtPublic/?q=node/48"
PORTAL_HOME = "https://webportal.placerco.org/eCourtPublic/"
USER_AGENT = (
    "Mozilla/5.0 (compatible; HammondProbateMonitor/1.0; "
    "+local research digest)"
)
# Drupal input names on the public Case Search form (node/48).
CASE_NUMBER_FIELD = "data(110134)"
FILED_FROM_FIELD = "data(110135)"
FILED_TO_FIELD = "data(110135_right)"
REQUIRED_SEARCH_FIELDS = (CASE_NUMBER_FIELD, FILED_FROM_FIELD, FILED_TO_FIELD)


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _section(text: str, start: str, *ends: str) -> str:
    low = text.lower()
    i = low.find(start.lower())
    if i < 0:
        return ""
    rest = text[i + len(start) :]
    cut = len(rest)
    low_rest = rest.lower()
    for end in ends:
        j = low_rest.find(end.lower())
        if j >= 0:
            cut = min(cut, j)
    return rest[:cut].strip()


class ECourtClient:
    def __init__(self, pause: float = 1.0) -> None:
        self.pause = pause
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _form_payload(self) -> tuple[str, dict]:
        resp = self.session.get(PORTAL_SEARCH, timeout=45)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise RuntimeError("eCourt search form not found")
        data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                data[name] = inp.get("value") or ""
        action = urljoin(PORTAL_HOME, form.get("action") or "?q=node/48")
        missing = [name for name in REQUIRED_SEARCH_FIELDS if name not in data]
        if missing:
            raise RuntimeError(
                "eCourt search form is missing expected fields "
                f"{missing}; the portal HTML may have changed."
            )
        return action, data

    def search_case(
        self,
        case_number: str,
        filed_from: str | None = None,
        filed_to: str | None = None,
    ) -> dict | None:
        year = datetime.now().year
        filed_from = filed_from or f"01/01/{year - 2}"
        filed_to = filed_to or f"12/31/{year + 1}"
        action, data = self._form_payload()
        data["data(110131)"] = ""
        data["data(110132)"] = ""
        data["data(110133)"] = ""
        data[CASE_NUMBER_FIELD] = case_number
        data[FILED_FROM_FIELD] = filed_from
        data[FILED_TO_FIELD] = filed_to
        data["op"] = "Search"
        resp = self.session.post(action, data=data, timeout=45)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [td.get_text(" ", strip=True) for td in rows[0].find_all(["th", "td"])]
            if "Case Number" not in headers:
                continue
            for tr in rows[1:]:
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(cells) < 4 or case_number.upper() not in cells[0].upper():
                    continue
                link = tr.find("a", href=True)
                href = urljoin(PORTAL_HOME, link["href"]) if link else ""
                return {
                    "case_number": cells[0],
                    "caption": cells[1] if len(cells) > 1 else "",
                    "filed": cells[2] if len(cells) > 2 else "",
                    "case_type": cells[3] if len(cells) > 3 else "",
                    "category": cells[4] if len(cells) > 4 else "",
                    "next_event": cells[5] if len(cells) > 5 else "",
                    "previous_event": cells[6] if len(cells) > 6 else "",
                    "court_status": cells[7] if len(cells) > 7 else "",
                    "court_url": href,
                }
        return None

    def fetch_summary(self, court_url: str) -> dict:
        resp = self.session.get(court_url, timeout=45)
        resp.raise_for_status()
        if "Page not found" in resp.text:
            return {"raw_text": "", "error": "case summary 404"}
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text("\n", strip=True)
        detail = parse_summary(text)
        files = parse_document_table(soup)
        if files:
            detail["document_files"] = files
            detail["documents"] = [
                f"{item['date']} {item['name']}".strip() if item.get("date") else item["name"]
                for item in files
            ]
        return detail

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        resp = self.session.get(url, timeout=90)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return dest

    def enrich(self, case_number: str, year: int | None = None) -> dict:
        year = year if year is not None else datetime.now().year
        time.sleep(self.pause)
        hit = self.search_case(
            case_number,
            filed_from=f"01/01/{year - 2}",
            filed_to=f"12/31/{year + 1}",
        )
        if not hit:
            return {"found": False, "case_number": case_number}
        detail = {}
        if hit.get("court_url"):
            time.sleep(self.pause)
            detail = self.fetch_summary(hit["court_url"])
        return {"found": True, **hit, **detail}


def parse_document_table(soup, base: str = PORTAL_HOME) -> list[dict]:
    docs: list[dict] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if headers[:3] != ["name", "date", "download"]:
            continue
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            name = tds[0].get_text(" ", strip=True)
            date = tds[1].get_text(" ", strip=True)
            link = tds[2].find("a", href=True)
            href = urljoin(base, link["href"]) if link else ""
            file_id = ""
            if href:
                m = re.search(r"downloadFile/(\d+)", href)
                file_id = m.group(1) if m else ""
            docs.append(
                {
                    "name": name,
                    "date": date,
                    "url": href,
                    "file_id": file_id,
                    "available": bool(href),
                }
            )
    return docs


JUNK_LINES = {
    "open",
    "view person",
    "more actions",
    "add item",
    "download",
    "download:",
    "unavailable",
    "documents",
    "name",
    "date",
    "document register",
    "attorney",
    "date assigned",
    "assignment type",
    "status",
    "representing/on behalf of",
    "current",
    "date/time",
    "type",
    "result",
    "official",
    "location",
    "next hearing date & time",
    "hearing type",
    "courtroom location",
    "future court hearings",
    "all court hearings",
    "invoices and payments",
    "parties",
}

LONG_HEARING_RE = re.compile(
    r"^[A-Z][a-z]+ \d{1,2}, \d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)\b",
    re.I,
)
DOCKET_HEARING_RE = re.compile(
    r"^\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)\b",
    re.I,
)
DATE_ONLY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
FILED_ON_RE = re.compile(r"filed on\s+(\d{2}/\d{2}/\d{4})", re.I)
FEE_AMT_RE = re.compile(
    r"Total Amount:\s*(?P<amt>\$[0-9,.]+)\s*Balance:\s*(?P<bal>\$[0-9,.]+)",
    re.I,
)


def _lines(block: str) -> list[str]:
    return [_clean(x) for x in (block or "").splitlines() if _clean(x)]


def _is_junk(line: str) -> bool:
    low = line.lower()
    if low in JUNK_LINES:
        return True
    if low.startswith("to view unavailable"):
        return True
    if low.startswith("portal case"):
        return True
    return False


def parse_summary(text: str) -> dict:
    parties_blk = _section(text, "Parties", "Future Court Hearings", "All Court Hearings")
    parties = []
    for line in _lines(parties_blk):
        if _is_junk(line) or " - " not in line:
            continue
        parties.append(re.sub(r"\s+-\s+", " — ", line))
    seen: set[str] = set()
    uniq_parties = []
    decedent_names = {
        p.split("—", 1)[-1].strip().lower()
        for p in parties
        if p.lower().startswith("decedent")
    }
    for p in parties:
        if p in seen:
            continue
        role, _, name = p.partition(" — ")
        if role.strip().lower() == "petitioner" and name.strip().lower() in decedent_names:
            continue
        seen.add(p)
        uniq_parties.append(p)

    future_blk = _section(text, "Future Court Hearings", "All Court Hearings", "Document Register")
    hearings = []
    buf: list[str] = []
    for line in _lines(future_blk):
        if _is_junk(line):
            continue
        if LONG_HEARING_RE.match(line) and buf:
            hearings.append(" — ".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        hearings.append(" — ".join(buf))
    # drop exact duplicate calendar rows
    hearings = list(dict.fromkeys(hearings))

    all_blk = _section(text, "All Court Hearings", "Document Register")
    filed_dates = list(dict.fromkeys(FILED_ON_RE.findall(all_blk)))
    filed = " · ".join(filed_dates)
    past = []
    buf = []
    for line in _lines(all_blk):
        if _is_junk(line) or line.lower().startswith("s-pr-") or FILED_ON_RE.search(line):
            continue
        if DOCKET_HEARING_RE.match(line) and buf:
            past.append(" — ".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        past.append(" — ".join(buf))
    past = [p for p in past if DOCKET_HEARING_RE.match(p.split(" — ", 1)[0])]

    docs_blk = _section(text, "Document Register", "Attorney", "Invoices and Payments")
    docs = []
    doc_lines = [x for x in _lines(docs_blk) if not _is_junk(x)]
    i = 0
    while i < len(doc_lines):
        line = doc_lines[i]
        if DATE_ONLY_RE.match(line):
            i += 1
            continue
        date = ""
        if i + 1 < len(doc_lines) and DATE_ONLY_RE.match(doc_lines[i + 1]):
            date = doc_lines[i + 1]
            i += 2
        else:
            i += 1
        docs.append(f"{date} {line}".strip() if date else line)

    atty_blk = _section(text, "Attorney", "Invoices and Payments", "Back to Top")
    attorneys = []
    atty_lines = [x for x in _lines(atty_blk) if not _is_junk(x)]
    i = 0
    while i < len(atty_lines):
        line = atty_lines[i]
        assigned = line if DATE_ONLY_RE.match(line) else ""
        if assigned:
            i += 1
            if i >= len(atty_lines):
                break
            name = atty_lines[i]
            i += 1
        else:
            name = line
            i += 1
        name = _split_counsel(name)
        if assigned:
            attorneys.append(f"{assigned} {name} (Current)")
        else:
            attorneys.append(name)

    fees_blk = _section(text, "Invoices and Payments", "Back to Top", "Copyright")
    fees = []
    fee_lines = [x for x in _lines(fees_blk) if not _is_junk(x)]
    i = 0
    while i < len(fee_lines):
        line = fee_lines[i]
        if DATE_ONLY_RE.match(line) and i + 1 < len(fee_lines):
            date = line
            desc = fee_lines[i + 1]
            i += 2
            if i < len(fee_lines) and re.match(rf"^{re.escape(date)}\s+\$", fee_lines[i]):
                i += 1
            amt = FEE_AMT_RE.search(desc)
            label = re.split(r"\s+-\s+Total Amount", desc, maxsplit=1)[0].strip(" -")
            if amt:
                fees.append(f"{date} {label} — {amt.group('amt')} paid (balance {amt.group('bal')})")
            else:
                fees.append(f"{date} {desc}")
            continue
        i += 1

    caption = ""
    m = re.search(r"(In [Rr]e the Estate of[^\n]+)", text)
    if m:
        caption = _clean(m.group(1))

    return {
        "caption": caption,
        "parties": uniq_parties,
        "hearings": hearings,
        "hearing_history": past,
        "filed_from_docket": filed,
        "documents": docs,
        "court_attorneys": attorneys,
        "fees": fees,
        "raw_text": text,
    }


def _split_counsel(name: str) -> str:
    m = re.match(
        r"^([A-Za-z'.\-]+,\s+[A-Za-z'.\-]+(?:\s+(?:Jr\.|Sr\.|[A-Za-z'.\-]+))?)\s+(.+)$",
        name,
    )
    if m and len(m.group(2)) > 2 and not m.group(2).startswith("Jr"):
        firm = m.group(2)
        if firm.startswith("Jr.") or firm.startswith("Sr."):
            who = f"{m.group(1)} {firm.split(' ', 1)[0]}"
            firm = firm.split(" ", 1)[1] if " " in firm else ""
            return f"{who} — {firm}" if firm else who
        return f"{m.group(1)} — {m.group(2)}"
    m = re.match(
        r"^([A-Za-z'.\-]+,\s+[A-Za-z'.\-]+(?:\s+[A-Za-z'.\-]+){0,2}\s+Jr\.)\s+(.+)$",
        name,
    )
    if m:
        return f"{m.group(1)} — {m.group(2)}"
    return name
