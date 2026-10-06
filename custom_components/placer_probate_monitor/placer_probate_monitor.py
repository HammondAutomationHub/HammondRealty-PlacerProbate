#!/usr/bin/env python3
"""Daily Placer County probate-notice monitor.

Pulls CNPA public notices for "NOTICE OF PETITION TO ADMINISTER ESTATE"
in Placer County, extracts structured fields, tracks first-seen cases,
and emails an HTML + text report.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


def _progress(step: str, message: str, **extra) -> None:
    try:
        from .job_progress import report_progress
    except ImportError:
        from job_progress import report_progress

    report_progress(step, message, **extra)

def get_tz():
    return ZoneInfo(os.environ.get("PROBATE_TZ", "America/Los_Angeles"))
BASE_SEARCH = "https://www.capublicnotice.com/search/query"
NOTICE_HOME = "https://www.capublicnotice.com"
USER_AGENT = (
    "PlacerProbateMonitor/1.0 "
    "(personal research; +local daily digest)"
)
CASE_RE = re.compile(r"\bS-PR-0*\d+\b", re.I)
ESTATE_RE = re.compile(
    r"NOTICE OF PETITION TO ADMINISTER ESTATE OF\s+"
    r"(?P<name>.+?)(?:\s+CASE NO\.|\s+\d+\.\s+To all heirs)",
    re.I | re.S,
)
AKA_LINE_RE = re.compile(
    r"interested in the will or estate, or both, of:\s*(?P<name>.+?)(?:\s*\d+\.\s|\s*$)",
    re.I | re.S,
)
PETITIONER_RE = re.compile(
    r"(?:A PETITION FOR PROBATE has been filed by|PETITION FOR PROBATE has been filed by)\s*:\s*"
    r"(?P<name>.+?)\s+in the Superior Court",
    re.I | re.S,
)
COURT_RE = re.compile(
    r"Superior Court of California,\s*County of\s+(?P<county>[A-Z ]+)",
    re.I,
)
HEARING_RE = re.compile(
    r"A HEARING on the petition will be held in this court as follows:\s*"
    r"(?P<when>.+?)(?:\s+\d+\.\s+IF YOU OBJECT|\s*$)",
    re.I | re.S,
)
ATTORNEY_RE = re.compile(
    r"(?:Attorney for Petitioner|ATTORNEY FOR PETITIONER)\s*:\s*(?P<atty>.+?)(?:\nPUBLISHED|\s*$)",
    re.I | re.S,
)
PUBLISHED_RE = re.compile(r"PUBLISHED IN\s+(?P<pub>.+)", re.I)
WILL_RE = re.compile(r"will and codicils, if any, be admitted to probate", re.I)
IAEA_RE = re.compile(r"Independent Administration of Estates Act", re.I)
PHONE_RE = re.compile(r"(?:Phone(?:\s*No\.)?|Tel)\s*:\s*([0-9().\-\s]{7,20})", re.I)


@dataclass
class Notice:
    case_number: str
    decedent: str
    petitioner: str
    court_county: str
    hearing: str
    attorney: str
    attorney_phone: str
    newspaper: str
    post_date: str
    publication_line: str
    will_offered: bool
    iaea_requested: bool
    refcode: str
    advert_id: str
    notice_url: str
    snippet: str
    raw_text: str
    first_seen: bool = False
    status: str = "repeat"  # new | repeat | missing_case

    def sort_key(self) -> tuple:
        return (0 if self.first_seen else 1, self.post_date or "", self.case_number)


def today_local() -> date:
    return datetime.now(get_tz()).date()


def default_window(lookback_days: int, lookahead_days: int) -> tuple[date, date]:
    start = today_local() - timedelta(days=lookback_days)
    end = today_local() + timedelta(days=lookahead_days)
    return start, end


def search_url(start: date, end: date, page: int = 0, size: int = 24) -> str:
    params = {
        "page": page,
        "size": size,
        "view": "list",
        "showExtended": "false",
        "startRange": "",
        "keywords": os.environ.get(
            "PROBATE_KEYWORDS", '"NOTICE OF PETITION TO ADMINISTER ESTATE"'
        ),
        "firstDate": start.strftime("%m/%d/%Y"),
        "lastDate": end.strftime("%m/%d/%Y"),
        "_categories": "1",
        "county": os.environ.get("PROBATE_COUNTY", "Placer"),
        "ordering": "BY_DATE_DEC",
    }
    return f"{BASE_SEARCH}?{urlencode(params)}"


def fetch_page(url: str, timeout: int = 45) -> str:
    resp = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" ,;.")
    value = re.sub(r"\s+\d+\.\s*$", "", value)
    return value.strip(" ,;.")


def normalize_post_date(value: str) -> str:
    """Store publication dates as YYYY-MM-DD so they sort across years."""
    raw = re.sub(r"\s+", " ", value or "").strip()
    if not raw:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            continue
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def http_url(value: str) -> str:
    text = (value or "").strip()
    if re.match(r"^https?://", text, re.I):
        return text
    return ""


def first_match(pattern: re.Pattern, text: str, group: str | int = 0) -> str:
    m = pattern.search(text)
    if not m:
        return ""
    if isinstance(group, str):
        return clean_name(m.group(group))
    return clean_name(m.group(group))


def extract_decedent(text: str) -> str:
    aka = first_match(AKA_LINE_RE, text, "name")
    if aka:
        return aka.rstrip(",")
    header = first_match(ESTATE_RE, text, "name")
    return header


def extract_case(text: str) -> str:
    matches = CASE_RE.findall(text)
    if not matches:
        return ""
    # Normalize to the longest / last official form
    raw = matches[-1].upper()
    m = re.search(r"S-PR-(\d+)", raw)
    if not m:
        return raw
    return f"S-PR-{int(m.group(1)):07d}"


def parse_card(card) -> Notice | None:
    desc = card.select_one(".description")
    if not desc:
        return None
    raw = desc.get_text("\n", strip=True)
    raw_flat = re.sub(r"[ \t]+", " ", raw)
    if "PETITION TO ADMINISTER ESTATE" not in raw_flat.upper():
        return None

    heading = card.select_one(".panel-heading h4")
    newspaper = heading.get_text(strip=True) if heading else ""
    time_el = card.select_one("time")
    post_date = ""
    if time_el is not None:
        raw_date = (time_el.get("datetime") or time_el.get_text(strip=True))[:10]
        if "Post Date" in (time_el.get_text() or ""):
            raw_date = time_el.get_text(strip=True).replace("Post Date:", "").strip()
        post_date = normalize_post_date(raw_date)

    ref = card.select_one(".refcode")
    refcode = re.sub(r"^Refcode:\s*", "", ref.get_text(strip=True) if ref else "")
    advert_inputs = card.select("input[id^=advertId_]")
    advert_id = advert_inputs[0]["value"] if advert_inputs else ""
    notice_url = f"{NOTICE_HOME}/advert/-{advert_id}" if advert_id else search_url(*default_window(21, 21))

    atty = first_match(ATTORNEY_RE, raw, "atty")
    phone = first_match(PHONE_RE, raw, 1)
    if not phone:
        phone_m = re.search(r"(\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4})", atty)
        phone = phone_m.group(1) if phone_m else ""

    notice = Notice(
        case_number=extract_case(raw_flat),
        decedent=extract_decedent(raw_flat),
        petitioner=first_match(PETITIONER_RE, raw_flat, "name"),
        court_county=first_match(COURT_RE, raw_flat, "county"),
        hearing=first_match(HEARING_RE, raw, "when"),
        attorney=re.sub(r"\s+", " ", atty),
        attorney_phone=phone,
        newspaper=newspaper,
        post_date=post_date,
        publication_line=first_match(PUBLISHED_RE, raw_flat, "pub"),
        will_offered=bool(WILL_RE.search(raw_flat)),
        iaea_requested=bool(IAEA_RE.search(raw_flat)),
        refcode=refcode,
        advert_id=advert_id,
        notice_url=notice_url,
        snippet=raw_flat[:280],
        raw_text=raw,
        status="missing_case" if not extract_case(raw_flat) else "repeat",
    )
    return notice


def parse_html(page_html: str) -> list[Notice]:
    soup = BeautifulSoup(page_html, "html.parser")
    cards = soup.select("div.panel.panel-result")
    notices: list[Notice] = []
    for card in cards:
        parsed = parse_card(card)
        if parsed:
            notices.append(parsed)
    return notices


def paginate(start: date, end: date, max_pages: int | None = None) -> tuple[list[Notice], list[str]]:
    if max_pages is None:
        max_pages = int(os.environ.get("PROBATE_MAX_PAGES", "10"))
    collected: list[Notice] = []
    urls: list[str] = []
    last_full = False
    for page in range(max_pages):
        url = search_url(start, end, page=page)
        urls.append(url)
        _progress(
            "cnpa",
            f"Searching CNPA notices (page {page + 1} of up to {max_pages})…",
            cnpa_page=page + 1,
            cnpa_max_pages=max_pages,
        )
        html_text = fetch_page(url)
        batch = parse_html(html_text)
        collected.extend(batch)
        soup = BeautifulSoup(html_text, "html.parser")
        # Site uses 0-based page in query, hidden #page starts at 1 after first view.
        card_count = len(soup.select("div.panel.panel-result"))
        last_full = card_count >= 24
        if card_count < 24:
            break
        load_more = soup.select_one("#loadMore")
        if load_more and "disabled" in (load_more.get("class") or []):
            break
    else:
        if last_full:
            print(
                f"Warning: hit {max_pages}-page cap; later notices may be missing.",
                file=sys.stderr,
            )
    return collected, urls


def dedupe(notices: Iterable[Notice]) -> list[Notice]:
    """Keep the newest publication of each case number."""
    by_case: dict[str, Notice] = {}
    for notice in notices:
        key = notice.case_number or f"NOCASE:{notice.advert_id or notice.refcode}"
        existing = by_case.get(key)
        if existing is None or (notice.post_date or "") > (existing.post_date or ""):
            by_case[key] = notice
    unique = list(by_case.values())
    unique.sort(key=lambda n: (n.post_date or "", n.case_number), reverse=True)
    return unique


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"cases": {}}
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        backup = path.with_name(path.name + ".corrupt")
        backup.write_text(raw, encoding="utf-8")
        raise SystemExit(
            f"State file {path} is not valid JSON ({exc}). "
            f"A copy was written to {backup}. Fix or restore {path} before re-running "
            "so existing cases are not re-flagged as new."
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("cases", {}), dict):
        raise SystemExit(
            f"State file {path} does not contain a JSON object with a 'cases' map."
        )
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def listing_from_row(row: dict, run_date: str) -> dict:
    case = str(row.get("case_number") or row.get("advert_id") or "").strip()
    petitioner = (
        str(row.get("petitioner") or "").strip()
        or str(row.get("petitioner_name") or "").strip()
    )
    decedent = (
        str(row.get("decedent") or "").strip()
        or str(row.get("decedent_name") or "").strip()
    )
    return {
        "case_number": case,
        "date": str(row.get("post_date") or row.get("filed") or "").strip(),
        "filed": str(row.get("filed") or row.get("filed_from_docket") or "").strip(),
        "source": "Placer County",
        "source_id": "placer",
        "petitioner": petitioner,
        "decedent": decedent,
        "decedent_address": str(row.get("decedent_residence") or "").strip(),
        "petitioner_address": str(
            row.get("mailing_address") or ""
        ).strip(),
        "hearing": str(row.get("next_event") or row.get("hearing") or "").strip(),
        "newspaper": str(row.get("newspaper") or "").strip(),
        "notice_url": str(row.get("notice_url") or "").strip(),
        "court_url": str(row.get("court_url") or "").strip(),
        "status": str(row.get("status") or "").strip(),
        "last_collected": run_date,
    }


def _read_listings_catalog(path: Path) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    if not path.exists():
        return catalog
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return catalog
    items = payload.get("listings") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return catalog
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("case_number") or "").strip()
        if key:
            catalog[key] = item
    return catalog


def merge_listings(path: Path, rows: list[dict], run_date: str) -> None:
    catalog = _read_listings_catalog(path)
    for row in rows:
        rec = listing_from_row(row, run_date)
        key = rec.get("case_number")
        if not key:
            continue
        prev = catalog.get(key) or {}
        merged = dict(prev)
        for field, value in rec.items():
            if value not in (None, "", [], {}):
                merged[field] = value
            elif field not in merged:
                merged[field] = value
        merged["first_collected"] = prev.get("first_collected") or run_date
        merged["last_collected"] = run_date
        catalog[key] = merged
    listings = sorted(
        catalog.values(),
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("case_number") or ""),
        ),
        reverse=True,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"updated": run_date, "count": len(listings), "listings": listings}, indent=2),
        encoding="utf-8",
    )


def mark_new(notices: list[Notice], state: dict, run_date: str) -> list[Notice]:
    cases = state.setdefault("cases", {})
    for notice in notices:
        key = notice.case_number or notice.advert_id
        if not key:
            notice.first_seen = True
            notice.status = "missing_case"
            continue
        if key not in cases:
            notice.first_seen = True
            notice.status = "new"
            cases[key] = {
                "first_seen": run_date,
                "decedent": notice.decedent,
                "last_seen": run_date,
                "newspaper": notice.newspaper,
            }
        else:
            notice.first_seen = False
            notice.status = "repeat"
            cases[key]["last_seen"] = run_date
    state["last_run"] = run_date
    return notices


def yesno(flag: bool) -> str:
    return "Yes" if flag else "No"


def build_text(notices: list[Notice], start: date, end: date, urls: list[str]) -> str:
    new_items = [n for n in notices if n.first_seen]
    lines = [
        f"Hammond IT Consulting — Blake Hammond Realty",
        f"Placer County probate petition notices",
        f"Window: {start.isoformat()} to {end.isoformat()}",
        f"Unique estates: {len(notices)}  |  New today: {len(new_items)}",
        "",
    ]
    if not notices:
        lines.append("No matching notices in this window.")
        lines.append("Query:")
        lines.extend(urls)
        return "\n".join(lines)

    for n in sorted(notices, key=lambda x: x.sort_key()):
        tag = "NEW" if n.first_seen else "SEEN"
        lines += [
            f"[{tag}] {n.decedent or '(name not parsed)'}  {n.case_number}",
            f"  Petitioner: {n.petitioner or '—'}",
            f"  Hearing:    {n.hearing or '—'}",
            f"  Court:      {n.court_county or '—'}",
            f"  Will: {yesno(n.will_offered)}   IAEA: {yesno(n.iaea_requested)}",
            f"  Attorney:   {n.attorney or '—'}",
            f"  Phone:      {n.attorney_phone or '—'}",
            f"  Paper:      {n.newspaper}  posted {n.post_date}",
            f"  Pub line:   {n.publication_line or '—'}",
            f"  Notice:     {n.notice_url}",
            "",
        ]
    lines += [
        "Watchlist (look up in Placer Assessor / Recorder):",
        *[f"  - {n.decedent} ({n.case_number})" for n in notices if n.decedent],
        "",
        "A published petition does not prove a house is in the estate.",
        "Match the decedent name to title before treating it as a property lead.",
    ]
    return "\n".join(lines)


def row_html(n: Notice) -> str:
    badge = (
        '<span style="background:#0b6;color:#fff;padding:2px 8px;border-radius:10px;font-size:12px;">NEW</span>'
        if n.first_seen
        else '<span style="background:#888;color:#fff;padding:2px 8px;border-radius:10px;font-size:12px;">SEEN</span>'
    )
    return f"""
    <tr>
      <td>{badge}</td>
      <td><strong>{html.escape(n.decedent or "—")}</strong><br>
          <a href="{html.escape(http_url(n.notice_url) or "#")}">{html.escape(n.case_number or "no case #")}</a></td>
      <td>{html.escape(n.petitioner or "—")}</td>
      <td>{html.escape(n.hearing or "—")}</td>
      <td>{yesno(n.will_offered)} / {yesno(n.iaea_requested)}</td>
      <td>{html.escape(n.attorney or "—")}<br>{html.escape(n.attorney_phone or "")}</td>
      <td>{html.escape(n.newspaper or "—")}<br>{html.escape(n.post_date or "")}</td>
    </tr>
    """


def build_html(notices: list[Notice], start: date, end: date, urls: list[str]) -> str:
    new_count = sum(1 for n in notices if n.first_seen)
    rows = "\n".join(row_html(n) for n in sorted(notices, key=lambda x: x.sort_key()))
    watch = "".join(
        f"<li>{html.escape(n.decedent)} — {html.escape(n.case_number)}</li>"
        for n in notices
        if n.decedent
    )
    empty = "<p>No matching notices in this window.</p>" if not notices else ""
    query = "<br>".join(html.escape(u) for u in urls)
    return f"""<!DOCTYPE html>
<html><body style="font-family:Georgia,serif;color:#222;max-width:960px;">
  <p style="letter-spacing:.08em;font-size:12px;color:#8a6d2b;margin:0 0 4px;">HAMMOND IT CONSULTING · BLAKE HAMMOND REALTY</p>
  <h2>Placer County probate petition notices</h2>
  <p>Window {start.isoformat()} → {end.isoformat()} &nbsp;|&nbsp;
     Unique estates: <strong>{len(notices)}</strong> &nbsp;|&nbsp;
     New since last run: <strong>{new_count}</strong></p>
  {empty}
  <table cellpadding="8" cellspacing="0" border="1" style="border-collapse:collapse;width:100%;font-size:14px;">
    <thead style="background:#f3f3f3;">
      <tr>
        <th>Status</th><th>Decedent / case</th><th>Petitioner</th>
        <th>Hearing</th><th>Will / IAEA</th><th>Attorney</th><th>Source</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <h3>Assessor watchlist</h3>
  <p>Look these names up in the Placer Assessor and Recorder. A petition is not proof of a house.</p>
  <ul>{watch or "<li>None</li>"}</ul>
  <p style="color:#666;font-size:12px;">Query used:<br>{query}</p>
</body></html>
"""


def guess_petition(portal: dict, notice: Notice) -> str:
    for doc in portal.get("documents") or []:
        if doc.lower().startswith("20") or "petition" in doc.lower():
            if "petition" in doc.lower():
                return doc
    if notice.will_offered:
        return "Will offered in the published notice"
    return "Letters / administration (see notice)"


def enrich_notices(notices: list[Notice], year: int, docs_dir: Path | None = None) -> list[dict]:
    try:
        from .ecourt_client import ECourtClient
        from .petition_parse import (
            contact_fields,
            looks_like_duties_form,
            looks_like_probate_petition,
            merge_petitioner_contact,
            parse_de111_pdf,
            parse_de147_pdf,
        )
    except ImportError:
        from ecourt_client import ECourtClient
        from petition_parse import (
            contact_fields,
            looks_like_duties_form,
            looks_like_probate_petition,
            merge_petitioner_contact,
            parse_de111_pdf,
            parse_de147_pdf,
        )

    client = ECourtClient(pause=float(os.environ.get("ECOURT_PAUSE", "1.2")))
    rows = []
    total = len(notices)
    for index, notice in enumerate(notices, 1):
        _progress(
            "ecourt",
            f"eCourt {index}/{total}: {notice.case_number or 'no case number'}",
            ecourt_index=index,
            ecourt_total=total,
            case_number=notice.case_number,
        )
        portal = {"found": False}
        if notice.case_number:
            try:
                portal = client.enrich(notice.case_number, year=year)
            except requests.RequestException as exc:
                portal = {"found": False, "error": str(exc), "case_number": notice.case_number}
        if not isinstance(portal, dict):
            portal = {
                "found": False,
                "case_number": notice.case_number,
                "error": "empty_portal",
            }
        if docs_dir and notice.case_number:
            case_dir = docs_dir / re.sub(r"[^\w\-]+", "_", notice.case_number)
            safe = re.sub(r"[^\w\-]+", "_", notice.case_number)
            skip_download = portal.get("error") == "ecourt_view_limit"
            petition_item = None
            duties_item = None
            if portal.get("found") and not skip_download:
                for item in portal.get("document_files") or []:
                    if not item.get("available"):
                        continue
                    name = item.get("name") or ""
                    if looks_like_probate_petition(name) and petition_item is None:
                        petition_item = item
                    if looks_like_duties_form(name) and duties_item is None:
                        duties_item = item
            de111: dict = {}
            de147: dict = {}
            dest111 = case_dir / f"{safe}_DE-111.pdf"
            if petition_item and not skip_download:
                try:
                    time.sleep(client.pause)
                    client.download(petition_item["url"], dest111)
                    portal["petition_url"] = petition_item["url"]
                except Exception as exc:  # noqa: BLE001
                    portal["petition_parse_error"] = str(exc)
            if dest111.is_file() and dest111.stat().st_size > 4 and dest111.read_bytes()[:4] == b"%PDF":
                try:
                    de111 = parse_de111_pdf(dest111, petitioner=notice.petitioner)
                    if de111.get("petitioner_name"):
                        portal["petitioner"] = de111["petitioner_name"]
                    if de111.get("decedent_name") and not portal.get("decedent"):
                        portal["decedent"] = de111["decedent_name"]
                    portal.update(de111)
                    portal["petition_pdf"] = str(dest111)
                    print(
                        f"DE-111 {notice.case_number}: "
                        f"mailing={de111.get('mailing_address') or '(empty)'} "
                        f"phone={de111.get('petitioner_phone') or '(empty)'} "
                        f"residence={de111.get('decedent_residence') or '(empty)'}",
                        flush=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    portal["petition_parse_error"] = str(exc)
            elif petition_item and dest111.is_file():
                portal["petition_parse_error"] = "download was not a PDF"
            dest147 = case_dir / f"{safe}_DE-147.pdf"
            if duties_item and not skip_download:
                try:
                    time.sleep(client.pause)
                    client.download(duties_item["url"], dest147)
                    portal["duties_url"] = duties_item["url"]
                except Exception as exc:  # noqa: BLE001
                    portal["duties_parse_error"] = str(exc)
            if dest147.is_file() and dest147.stat().st_size > 4 and dest147.read_bytes()[:4] == b"%PDF":
                try:
                    de147 = parse_de147_pdf(dest147)
                    portal["duties_pdf"] = str(dest147)
                    print(
                        f"DE-147 {notice.case_number}: "
                        f"mailing={de147.get('mailing_address') or '(empty)'} "
                        f"phone={de147.get('petitioner_phone') or '(empty)'} "
                        f"email={de147.get('petitioner_email') or '(empty)'}",
                        flush=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    portal["duties_parse_error"] = str(exc)
            elif duties_item and dest147.is_file():
                portal["duties_parse_error"] = "download was not a PDF"
            portal["contact_de111"] = contact_fields(de111)
            portal["contact_de147"] = contact_fields(de147)
            contact = merge_petitioner_contact(de111, de147)
            if contact:
                portal.update(contact)
                print(
                    f"contact {notice.case_number}: "
                    f"mailing={contact.get('mailing_address') or '(empty)'} "
                    f"phone={contact.get('petitioner_phone') or '(empty)'} "
                    f"email={contact.get('petitioner_email') or '(empty)'}",
                    flush=True,
                )
        row = asdict(notice)
        merged = {k: v for k, v in portal.items() if v not in (None, "", [], {})}
        if "status" in merged and "court_status" not in merged:
            merged["court_status"] = merged.pop("status")
        else:
            merged.pop("status", None)
        row.update(merged)
        row["status"] = notice.status
        row["first_seen"] = notice.first_seen
        row["found"] = bool(portal.get("found"))
        row["petition_guess"] = guess_petition(portal, notice)
        if not row.get("filed"):
            row["filed"] = portal.get("filed") or portal.get("filed_from_docket")
        rows.append(row)
    limit_cases = sorted(
        {
            str(row.get("case_number") or "")
            for row in rows
            if row.get("error") == "ecourt_view_limit" or row.get("ecourt_view_limit")
        }
        - {""}
    )
    if limit_cases:
        print(
            "ECOURT_VIEW_LIMIT source=placer source_name=Placer County "
            f"cases={','.join(limit_cases)}",
            flush=True,
        )
    return rows


def write_ecourt_alerts(path: Path, rows: list[dict]) -> dict:
    cases = sorted(
        {
            str(row.get("case_number") or "")
            for row in rows
            if row.get("error") == "ecourt_view_limit" or row.get("ecourt_view_limit")
        }
        - {""}
    )
    payload = {
        "error": "ecourt_view_limit" if cases else None,
        "source": "placer",
        "source_name": "Placer County",
        "cases": cases,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def send_email(subject: str, text_body: str, html_body: str, pdf_path: Path | None = None) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    mail_from = os.environ.get("MAIL_FROM", user)
    mail_to = [addr.strip() for addr in os.environ.get("MAIL_TO", "").split(",") if addr.strip()]

    if not mail_to:
        raise SystemExit("MAIL_TO is not set. Put recipient addresses in .env or the environment.")
    if not user or not password:
        raise SystemExit("SMTP_USER / SMTP_PASSWORD are not set.")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)
    if pdf_path and pdf_path.exists():
        part = MIMEApplication(pdf_path.read_bytes(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=pdf_path.name)
        msg.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.sendmail(mail_from, mail_to, msg.as_string())


def write_outputs(out_dir: Path, text_body: str, html_body: str, notices: list[Notice]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(get_tz()).strftime("%Y-%m-%d")
    (out_dir / f"report-{stamp}.txt").write_text(text_body, encoding="utf-8")
    (out_dir / f"report-{stamp}.html").write_text(html_body, encoding="utf-8")
    payload = [asdict(n) for n in notices]
    (out_dir / f"notices-{stamp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily Placer probate notice digest")
    p.add_argument("--lookback-days", type=int, default=21)
    p.add_argument("--lookahead-days", type=int, default=21)
    p.add_argument("--state-file", default="data/seen_cases.json")
    p.add_argument("--out-dir", default="data/reports")
    p.add_argument("--no-email", action="store_true", help="Parse and save files only")
    p.add_argument("--dry-run", action="store_true", help="Print and write report files; do not update state or email")
    p.add_argument("--skip-portal", action="store_true", help="CNPA only; skip eCourt lookups")
    p.add_argument("--no-pdf", action="store_true", help="Do not write the dossier PDF")
    p.add_argument(
        "--fub-verify-one",
        action="store_true",
        help="Create at most one new Follow Up Boss person, then skip remaining go-cases",
    )
    p.add_argument(
        "--fub-preview-one",
        action="store_true",
        help="Scrape and show one mapped go-case without posting to Follow Up Boss or updating seen state",
    )
    p.add_argument("--env-file", default=".env")
    return p.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    root = Path(__file__).resolve().parent
    load_env_file(root / args.env_file)
    if args.fub_preview_one:
        os.environ["FUB_PREVIEW_ONE"] = "1"
    if args.fub_verify_one:
        os.environ["FUB_VERIFY_ONLY"] = "1"

    start, end = default_window(args.lookback_days, args.lookahead_days)
    try:
        notices, urls = paginate(start, end)
    except requests.RequestException as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 2

    unique = dedupe(notices)
    state_path = Path(args.state_file)
    if not state_path.is_absolute():
        state_path = (root / args.state_file).resolve()
    else:
        state_path = state_path.resolve()
    state = load_state(state_path)
    run_date = today_local().isoformat()
    unique = mark_new(unique, state, run_date)
    os.environ.setdefault("PPM_PROGRESS_PATH", str(state_path.parent / "job_progress.json"))
    new_count = sum(1 for n in unique if n.first_seen)
    _progress(
        "cnpa_done",
        f"CNPA found {len(unique)} unique notices ({new_count} new in this window).",
        notices=len(unique),
        notice_count=len(unique),
        new_count=new_count,
    )

    text_body = build_text(unique, start, end, urls)
    html_body = build_html(unique, start, end, urls)
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = root / args.out_dir
    write_outputs(out_dir, text_body, html_body, unique)

    stamp = datetime.now(get_tz()).strftime("%Y-%m-%d")
    pdf_path = out_dir / f"Placer-Probate-Daily-Feed-{stamp}.pdf"
    rows = [asdict(n) for n in unique]
    if not args.skip_portal:
        print("Looking up each case on Placer eCourt Public…")
        _progress(
            "ecourt",
            f"Looking up {len(unique)} cases on Placer eCourt Public…",
            ecourt_total=len(unique),
        )
        rows = enrich_notices(unique, year=start.year, docs_dir=out_dir / "docs")
        (out_dir / f"dossiers-{stamp}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    else:
        _progress("ecourt_skip", "Skipping eCourt lookups.")
    write_ecourt_alerts(state_path.parent / "ecourt_alerts.json", rows)
    merge_listings(state_path.parent / "listings.json", rows, run_date)
    if not args.no_pdf:
        try:
            from .pdf_report import build_pdf
        except ImportError:
            from pdf_report import build_pdf

        _progress("pdf", "Building the daily PDF…")
        build_pdf(rows, pdf_path, today_local(), start, end)
        print(f"Wrote PDF {pdf_path}")
    else:
        pdf_path = None

    new_count = sum(1 for n in unique if n.first_seen)
    subject = (
        f"Placer probate notices — {run_date} — "
        f"{new_count} new / {len(unique)} unique"
    )
    print(text_body)

    if args.fub_preview_one:
        try:
            from .fub_client import preview_one_record
        except ImportError:
            from fub_client import preview_one_record

        _progress("preview", "Previewing one live extract (not posting to Follow Up Boss)…")
        preview = preview_one_record(
            rows, mapping_path=state_path.parent / "fub_mapping.yaml"
        )
        (state_path.parent / "fub_last.json").write_text(
            json.dumps(
                {
                    "posted": 0,
                    "updated": 0,
                    "skipped": len(preview.get("skips") or []),
                    "error": None,
                    "preview": True,
                    "verify_record": preview.get("verify_record"),
                    "verify_note": preview.get("verify_note"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("\nPreview only: Follow Up Boss not updated, seen-cases not updated.")
        _progress(
            "done",
            "Preview finished (Follow Up Boss not updated).",
            fub_posted=0,
            fub_updated=0,
            fub_skipped=len(preview.get("skips") or []),
        )
        return 0

    if args.dry_run:
        print("\nDry run: state and email not written.")
        return 0
    save_state(state_path, state)
    try:
        from .fub_client import export_new_leads
    except ImportError:
        from fub_client import export_new_leads

    _progress("fub", "Importing go-cases into Follow Up Boss…")
    fub_summary = export_new_leads(
        rows, state, mapping_path=state_path.parent / "fub_mapping.yaml"
    )
    posted = int(fub_summary.get("posted") or 0)
    updated = int(fub_summary.get("updated") or 0)
    skipped = int(fub_summary.get("skipped") or 0)
    _progress(
        "fub_done",
        f"Follow Up Boss: posted {posted}, updated {updated}, skipped {skipped}.",
        fub_posted=posted,
        fub_updated=updated,
        fub_skipped=skipped,
    )
    save_state(state_path, state)
    (state_path.parent / "fub_last.json").write_text(
        json.dumps(
            {
                "posted": fub_summary.get("posted"),
                "updated": fub_summary.get("updated"),
                "skipped": fub_summary.get("skipped"),
                "error": fub_summary.get("error"),
                "verify_case": fub_summary.get("verify_case"),
                "verify_person_id": fub_summary.get("verify_person_id"),
                "verify_record": fub_summary.get("verify_record"),
                "verify_note": fub_summary.get("verify_note"),
                "skips": fub_summary.get("skips") or [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.no_email:
        print(f"\nSaved state to {state_path}. Email skipped.")
        _progress(
            "done",
            f"Job finished. FUB posted {posted}, updated {updated}, skipped {skipped}.",
            fub_posted=posted,
            fub_updated=updated,
            fub_skipped=skipped,
        )
        return 0
    _progress("email", "Sending the daily email…")
    send_email(subject, text_body, html_body, pdf_path=pdf_path)
    print("\nEmail sent.")
    _progress(
        "done",
        f"Job finished. FUB posted {posted}, updated {updated}, skipped {skipped}.",
        fub_posted=posted,
        fub_updated=updated,
        fub_skipped=skipped,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
