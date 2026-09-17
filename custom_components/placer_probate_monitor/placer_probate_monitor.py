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
        from .petition_parse import looks_like_probate_petition, parse_de111_pdf
    except ImportError:
        from ecourt_client import ECourtClient
        from petition_parse import looks_like_probate_petition, parse_de111_pdf

    client = ECourtClient(pause=float(os.environ.get("ECOURT_PAUSE", "1.2")))
    rows = []
    for notice in notices:
        portal = {"found": False}
        if notice.case_number:
            try:
                portal = client.enrich(notice.case_number, year=year)
            except requests.RequestException as exc:
                portal = {"found": False, "error": str(exc), "case_number": notice.case_number}
        if docs_dir and portal.get("found"):
            case_dir = docs_dir / re.sub(r"[^\w\-]+", "_", notice.case_number)
            for item in portal.get("document_files") or []:
                if not (item.get("available") and looks_like_probate_petition(item.get("name") or "")):
                    continue
                file_id = item.get("file_id") or "petition"
                dest = case_dir / f"{file_id}_petition.pdf"
                try:
                    time.sleep(client.pause)
                    client.download(item["url"], dest)
                    if dest.read_bytes()[:4] == b"%PDF":
                        portal.update(parse_de111_pdf(dest))
                        portal["petition_pdf"] = str(dest)
                    else:
                        portal["petition_parse_error"] = "download was not a PDF"
                except Exception as exc:  # noqa: BLE001
                    portal["petition_parse_error"] = str(exc)
                break
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
    return rows


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

    start, end = default_window(args.lookback_days, args.lookahead_days)
    try:
        notices, urls = paginate(start, end)
    except requests.RequestException as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 2

    unique = dedupe(notices)
    state_path = (root / args.state_file).resolve()
    state = load_state(state_path)
    run_date = today_local().isoformat()
    unique = mark_new(unique, state, run_date)

    text_body = build_text(unique, start, end, urls)
    html_body = build_html(unique, start, end, urls)
    out_dir = root / args.out_dir
    write_outputs(out_dir, text_body, html_body, unique)

    stamp = datetime.now(get_tz()).strftime("%Y-%m-%d")
    pdf_path = out_dir / f"Placer-Probate-Daily-Feed-{stamp}.pdf"
    rows = [asdict(n) for n in unique]
    if not args.skip_portal:
        print("Looking up each case on Placer eCourt Public…")
        rows = enrich_notices(unique, year=start.year, docs_dir=out_dir / "docs")
        (out_dir / f"dossiers-{stamp}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if not args.no_pdf:
        try:
            from .pdf_report import build_pdf
        except ImportError:
            from pdf_report import build_pdf

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

    if args.dry_run:
        print("\nDry run: state and email not written.")
        return 0
    save_state(state_path, state)
    if args.no_email:
        print(f"\nSaved state to {state_path}. Email skipped.")
        return 0
    send_email(subject, text_body, html_body, pdf_path=pdf_path)
    print("\nEmail sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
