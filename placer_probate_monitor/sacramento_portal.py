#!/usr/bin/env python3
"""Sacramento Superior Court public-portal lookups.

Journal Technologies eCourt, not Placer's Tyler eCourt Public site.
Case-number search is node/429. The result link (node/430/id) is a
documents-only page and 404s if it is opened without the search session.
The full case summary is the same id on node/397 and can be opened directly.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PORTAL_BASE = "https://prod-portal-sacramento-ca.journaltech.com/public-portal/"
PORTAL_SEARCH = PORTAL_BASE + "?q=node/429"
PORTAL_LOGIN = PORTAL_BASE + "?q=user/login"
SUMMARY_NODE = "397"
USER_AGENT = (
    "Mozilla/5.0 (compatible; HammondProbateMonitor/1.0; "
    "+local research digest)"
)
CASE_ID_RE = re.compile(r"node/(?:397|430)/(\d+)")
DOC_VIEW_RE = re.compile(r"doc_view_(\d+)")
DOWNLOAD_FILE_RE = re.compile(r"downloadFile/(\d+)/(\d+)")
MATH_CAPTCHA_RE = re.compile(r"(\d+)\s*([+\-×x*])\s*(\d+)\s*=")


def _clean(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


class SacramentoPortal:
    def __init__(
        self,
        pause: float = 1.2,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.pause = pause
        self.username = (username if username is not None else os.environ.get("SACRAMENTO_PORTAL_USER") or "").strip()
        self.password = password if password is not None else os.environ.get("SACRAMENTO_PORTAL_PASSWORD") or ""
        self.logged_in = False
        self.login_error = ""
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _form_payload(self) -> tuple[str, dict]:
        resp = self.session.get(PORTAL_SEARCH, timeout=45)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form", id="ecp-searchform-form") or soup.find("form")
        if not form:
            raise RuntimeError("Sacramento case-search form not found")
        data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name and name != "op":
                data[name] = inp.get("value") or ""
        action = urljoin(PORTAL_BASE, form.get("action") or "?q=node/429")
        return action, data

    def search_case(self, case_number: str) -> dict | None:
        for operator in ("EQUALS", "CONTAINS"):
            action, data = self._form_payload()
            data["data(82311)"] = case_number
            data["data(82311_op)"] = operator
            data["op"] = "Search"
            resp = self.session.post(action, data=data, timeout=45)
            resp.raise_for_status()
            hit = _parse_search(resp.text, case_number)
            if hit:
                return hit
            time.sleep(self.pause)
        return None

    def ensure_login(self) -> bool:
        if self.logged_in:
            return True
        if not self.username or not self.password:
            self.login_error = "Sacramento portal username and password are not set."
            return False
        try:
            self.login()
        except Exception as exc:  # noqa: BLE001
            self.login_error = str(exc)
            return False
        return self.logged_in

    def login(self) -> None:
        resp = self.session.get(PORTAL_LOGIN, timeout=45)
        resp.raise_for_status()
        if session_is_logged_in(resp.text):
            self.logged_in = True
            self.login_error = ""
            return
        action, data = login_form_payload(resp.text, self.username, self.password)
        posted = self.session.post(action, data=data, timeout=45)
        posted.raise_for_status()
        if session_is_logged_in(posted.text):
            self.logged_in = True
            self.login_error = ""
            return
        self.logged_in = False
        raise RuntimeError("Sacramento portal login failed.")

    def fetch_summary(self, summary_id: str) -> dict:
        url = f"{PORTAL_BASE}?q=node/{SUMMARY_NODE}/{summary_id}"
        resp = self.session.get(url, timeout=45)
        resp.raise_for_status()
        if "could not be found" in resp.text or "Page not found" in resp.text:
            return {"error": "case summary 404", "court_url": url}
        parsed = parse_summary(resp.text)
        parsed["court_url"] = url
        files = parse_document_files(resp.text, summary_id)
        if files:
            parsed["document_files"] = files
            titles = [
                f"{item['date']} {item['name']}".strip() if item.get("date") else item["name"]
                for item in files
                if item.get("available")
            ]
            if titles:
                parsed["documents"] = titles
        return parsed

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        resp = self.session.get(url, timeout=90, allow_redirects=True)
        resp.raise_for_status()
        if "user/login" in (resp.url or "") or resp.content[:4] != b"%PDF":
            raise RuntimeError("Sacramento document download did not return a PDF.")
        dest.write_bytes(resp.content)
        return dest

    def enrich(self, case_number: str) -> dict:
        if self.username and self.password and not self.logged_in:
            self.ensure_login()
        time.sleep(self.pause)
        hit = self.search_case(case_number)
        if not hit:
            return {"found": False, "case_number": case_number}
        detail = {}
        if hit.get("summary_id"):
            time.sleep(self.pause)
            detail = self.fetch_summary(hit["summary_id"])
        merged = {"found": True, **hit, **detail}
        if detail.get("error"):
            merged["found"] = False
        if self.login_error and not self.logged_in:
            merged["portal_login_error"] = self.login_error
        merged["portal_logged_in"] = self.logged_in
        return merged


def _parse_search(html: str, case_number: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    by_id: dict[str, list[str]] = {}
    for link in soup.find_all("a", href=True):
        match = CASE_ID_RE.search(link["href"])
        if not match:
            continue
        text = _clean(link.get_text(" ", strip=True))
        if not text or text.lower() in {"case number", "case name"}:
            continue
        by_id.setdefault(match.group(1), []).append(text)
    wanted = case_number.upper()
    for summary_id, labels in by_id.items():
        if not any(wanted in label.upper() for label in labels):
            continue
        caption = next((label for label in labels if wanted not in label.upper()), "")
        return {
            "case_number": case_number,
            "caption": caption,
            "summary_id": summary_id,
            "court_url": f"{PORTAL_BASE}?q=node/{SUMMARY_NODE}/{summary_id}",
        }
    return None


def session_is_logged_in(html: str) -> bool:
    text = html or ""
    low = text.lower()
    if re.search(r"(?<![a-z-])logged-in(?![a-z-])", low):
        return True
    return ">logout<" in low or "q=user/logout" in low


def solve_math_captcha(html: str) -> int | None:
    match = MATH_CAPTCHA_RE.search(html or "")
    if not match:
        return None
    left, op, right = int(match.group(1)), match.group(2), int(match.group(3))
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    return left * right


def login_form_payload(html: str, username: str, password: str) -> tuple[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="user-login") or soup.find("form")
    if not form:
        raise RuntimeError("Sacramento portal login form not found.")
    data: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        data[name] = inp.get("value") or ""
    answer = solve_math_captcha(html)
    if answer is None:
        raise RuntimeError("Sacramento portal math CAPTCHA was not found in the login HTML.")
    data["name"] = username
    data["pass"] = password
    data["captcha_response"] = str(answer)
    data["op"] = data.get("op") or "Log in"
    action = urljoin(PORTAL_BASE, form.get("action") or "?q=user/login")
    return action, data


def document_is_blocked(name: str, image: str = "", blob: str = "") -> bool:
    text = " ".join(part for part in (name, image, blob) if part).lower()
    compact = re.sub(r"[^a-z0-9]+", "", text)
    if "not viewable" in text or "sealed" in text:
        return True
    if "confidential" in text:
        return True
    if "de147s" in compact:
        return True
    return False


def parse_document_files(html: str, summary_id: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    pane = soup.select_one("div.tabpane")
    table = pane.select_one("table.table") if pane else None
    if table is None:
        return []
    docs: list[dict] = []
    for tr in table.find_all("tr"):
        cells = [_clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        nonempty = [cell for cell in cells if cell]
        if len(nonempty) < 2:
            continue
        date = ""
        name = ""
        for cell in nonempty:
            if re.match(r"\d{2}/\d{2}/\d{4}", cell) and not date:
                date = cell
                continue
            if cell.lower() in {"view document", "not viewable", "image"}:
                continue
            if re.fullmatch(r"\d+", cell):
                continue
            if not name and not re.match(r"\d{2}/\d{2}/\d{4}", cell):
                name = cell
                break
        if not name:
            continue
        image = nonempty[-1] if nonempty else ""
        blob = " ".join(nonempty)
        blocked = document_is_blocked(name, image, blob)
        button = tr.find("button", attrs={"data-target": True})
        target = (button.get("data-target") if button else "") or ""
        match = DOC_VIEW_RE.search(target)
        file_id = match.group(1) if match else ""
        if not file_id:
            href = " ".join(a.get("href") or "" for a in tr.find_all("a", href=True))
            dl = DOWNLOAD_FILE_RE.search(href) or DOWNLOAD_FILE_RE.search(tr.decode())
            if dl:
                file_id = dl.group(1)
        available = bool(file_id) and not blocked and "view document" in image.lower()
        url = ""
        if available and summary_id:
            url = f"{PORTAL_BASE}?q=downloadFile/{file_id}/{summary_id}"
        docs.append(
            {
                "name": name,
                "date": date,
                "url": url,
                "file_id": file_id,
                "available": available,
            }
        )
    return docs


def _pane_rows(soup: BeautifulSoup, pane_index: int) -> list[list[str]]:
    panes = soup.select("div.tabpane")
    if pane_index >= len(panes):
        return []
    table = panes[pane_index].select_one("table.table")
    if not table:
        return []
    rows = []
    for tr in table.find_all("tr"):
        cells = [_clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        cells = [cell for cell in cells if cell]
        if not cells:
            continue
        head = cells[0].lower()
        if head in {"name", "filed / status date", "date", "filter rows"}:
            continue
        if head.startswith("view document") or "loading" in head:
            continue
        blob = " ".join(cells).lower()
        if "not viewable" in blob or "confidential" in blob:
            continue
        rows.append(cells)
    return rows


def _uniq(items: list[str]) -> list[str]:
    seen = set()
    unique = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _party_line(name: str, role: str) -> str:
    trimmed = re.sub(rf"\s*\({re.escape(role)}\)\s*$", "", name, flags=re.I).strip()
    if role:
        return f"{trimmed} — {role}"
    return trimmed


def parse_summary(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one("table.caseHeader")
    caption = ""
    case_type = ""
    category = ""
    courthouse = ""
    filed = ""
    next_event = ""
    department = ""
    if header:
        title_cell = header.select_one("td.caseheaderXLtext") or header.find("td")
        bolds = [_clean(b.get_text(" ", strip=True)) for b in header.find_all("b")]
        case_no = bolds[0] if bolds else ""
        if len(bolds) > 1:
            case_type = bolds[1]
        if title_cell:
            caption = _clean(title_cell.get_text(" ", strip=True))
            if case_no:
                caption = _clean(re.sub(rf"^{re.escape(case_no)}\s*", "", caption))
        for span in header.find_all("span"):
            title = _clean(span.get("title") or "")
            visible = _clean(span.get_text(" ", strip=True))
            if not title:
                continue
            if title.lower() == "date filed":
                match = re.search(r"(\d{2}/\d{2}/\d{4})", visible)
                filed = match.group(1) if match else filed
            elif title.lower().startswith("next event"):
                next_event = re.sub(r"^Next Event\s*", "", title, flags=re.I).strip()
            elif "courthouse" in title.lower() or "family relations" in title.lower():
                courthouse = title
            elif title.lower() not in {"date filed"} and len(title) > 12 and not category:
                category = title
        dept = re.search(r"DEPT\.?\s*\d+[^/\n]{0,40}", header.get_text(" ", strip=True), re.I)
        if dept:
            department = _clean(dept.group(0))

    documents = []
    filers = []
    for cells in _pane_rows(soup, 0):
        # date, name, filed by, pages, image
        if len(cells) < 2 or not re.match(r"\d{2}/\d{2}/\d{4}", cells[0]):
            continue
        documents.append(f"{cells[0]} {cells[1]}".strip())
        if len(cells) > 2 and cells[2] and cells[2].lower() not in {"clerk", "image"}:
            filers.append(cells[2])

    parties = []
    for cells in _pane_rows(soup, 2):
        name = cells[0]
        role = cells[2] if len(cells) > 2 else (cells[1] if len(cells) > 1 else "")
        if name.lower() == "aka/dba":
            continue
        parties.append(_party_line(name, role if not re.match(r"\d{2}/\d{2}/\d{4}", role) else ""))

    hearings = []
    history = []
    for cells in _pane_rows(soup, 3):
        if len(cells) < 3:
            continue
        name, when, status = cells[0], cells[1], cells[2]
        place = cells[3] if len(cells) > 3 else ""
        line = " — ".join(part for part in (when, name, status, place) if part)
        if status.lower() == "scheduled":
            hearings.append(line)
        else:
            history.append(line)

    parties = _uniq(parties)
    hearings = _uniq(hearings)
    history = _uniq(history)
    documents = _uniq(documents)
    if not next_event and hearings:
        next_event = hearings[0]
    previous_event = history[0] if history else ""

    attorneys = []
    for party in parties:
        if "attorney" in party.lower():
            attorneys.append(party)
    if not attorneys:
        for filer in filers:
            if re.search(r"\bSBN\b|attorney", filer, re.I):
                attorneys.append(filer)
    attorneys = _uniq(attorneys)

    return {
        "caption": caption,
        "case_type": case_type,
        "category": category,
        "courthouse": " — ".join(part for part in (courthouse, department) if part),
        "filed": filed,
        "filed_from_docket": filed,
        "next_event": next_event,
        "previous_event": previous_event,
        "parties": parties,
        "hearings": hearings,
        "hearing_history": history,
        "documents": documents,
        "court_attorneys": attorneys,
        "fees": [],
    }
