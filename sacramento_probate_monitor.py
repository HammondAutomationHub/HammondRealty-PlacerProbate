#!/usr/bin/env python3
"""Daily Sacramento County probate-notice monitor.

CNPA keyword is NOTICE OF PETITION; cards are kept only when the body
contains PETITION TO ADMINISTER ESTATE. Case numbers are YYPR######.
Court summaries are Journal Technologies node/397. Public petition and
duties PDFs are downloaded after portal login. Confidential Not Viewable
filings, including DE-147S, are not downloaded.

Placer's seen_cases.json, keywords, and eCourt path are not used here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import requests

try:
    from .datasources import petition_docs_dir, rescan_local_rows, stamp_fub_tags
    from .placer_probate_monitor import (
        Notice,
        build_html,
        build_text,
        dedupe,
        default_window,
        fetch_page,
        guess_petition,
        load_env_file,
        load_state,
        mark_new,
        merge_listings,
        notice_fields,
        paginate,
        refresh_digest_with_fub,
        save_state,
        send_email,
        today_local,
        write_outputs,
        _finish_fub,
        _finish_stored_test,
        _progress,
        _read_listings_catalog,
        get_tz,
    )
except ImportError:
    from datasources import petition_docs_dir, rescan_local_rows, stamp_fub_tags
    from placer_probate_monitor import (
        Notice,
        build_html,
        build_text,
        dedupe,
        default_window,
        fetch_page,
        guess_petition,
        load_env_file,
        load_state,
        mark_new,
        merge_listings,
        notice_fields,
        paginate,
        refresh_digest_with_fub,
        save_state,
        send_email,
        today_local,
        write_outputs,
        _finish_fub,
        _finish_stored_test,
        _progress,
        _read_listings_catalog,
        get_tz,
    )

COUNTY = "Sacramento"
KEYWORDS = '"NOTICE OF PETITION"'
SAC_CASE_RE = re.compile(r"\b(\d{2})[\s\-]*PR[\s\-]*(\d{3,8})\b", re.I)
SAC_COURT_RE = re.compile(r"COUNTY OF\s+SACRAMENTO", re.I)
LEGACY_CASE_RE = re.compile(r"\b34-\d{4}-\d{5,8}\b")
SOURCE_NOTE = (
    "Sources: capublicnotice.com keyword search in Sacramento County "
    "(NOTICE OF PETITION, kept only when the ad is a petition to administer an estate); "
    "prod-portal-sacramento-ca.journaltech.com public case search, then the node/397 case summary. "
    "Public DE-111 and DE-147 PDFs are downloaded after portal login. "
    "Confidential Not Viewable documents including DE-147S are not downloaded. "
    "List cards from the Sacramento Bee and the Observer are shortened; the full ad is read from the advert page."
)
INTRO = (
    "Each estate merges the published Notice of Petition to Administer Estate with the "
    "Sacramento Superior Court public case summary and public petition/duties PDFs. "
    "Confidential Not Viewable filings are skipped. "
    "A petition is not proof that real property is in the estate."
)


def portal_pause_seconds() -> float:
    raw = os.environ.get("SACRAMENTO_PORTAL_PAUSE") or os.environ.get("ECOURT_PAUSE") or "1.2"
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 1.2


def is_sacramento_court_notice(notice: Notice) -> bool:
    """True when the published notice names Sacramento Superior Court."""
    court = re.sub(r"\s+", " ", str(notice.court_county or "")).strip().upper()
    if court.startswith("SACRAMENTO"):
        return True
    blob = " ".join(
        part for part in (notice.raw_text, notice.snippet, notice.court_county) if part
    )
    return bool(SAC_COURT_RE.search(blob))


def collect_sacramento_cnpa_notices(
    start,
    end,
    *,
    max_pages: int | None = None,
) -> tuple[list[Notice], list[str], set[str]]:
    """Newspaper-county search plus an unscoped CNPA pass.

    CNPA ``county=Sacramento`` is the *newspaper's* county, not the court.
    That query is only one page of ads. A second pass omits ``county`` so
    Sacramento court petitions printed in other papers are not dropped, then
    callers keep those after hydrate via ``keep_sacramento_notices``.
    """
    if max_pages is None:
        max_pages = int(os.environ.get("PROBATE_MAX_PAGES", "10"))
    scoped, urls_a = paginate(
        start,
        end,
        county=COUNTY,
        keywords=KEYWORDS,
        case_extractor=extract_sacramento_case,
        max_pages=max_pages,
    )
    open_cap = max(int(max_pages), 80)
    unscoped, urls_b = paginate(
        start,
        end,
        county="",
        keywords=KEYWORDS,
        case_extractor=extract_sacramento_case,
        max_pages=open_cap,
    )
    scoped_keys = {notice.case_number or notice.advert_id for notice in scoped}
    merged = list(scoped)
    seen = set(scoped_keys)
    for notice in unscoped:
        key = notice.case_number or notice.advert_id
        if key in seen:
            continue
        seen.add(key)
        merged.append(notice)
    print(
        f"CNPA Sacramento newspaper-county ads {len(scoped)}; "
        f"unscoped extra cards {len(unscoped)}.",
        flush=True,
    )
    return merged, urls_a + urls_b, scoped_keys


def in_sacramento_scoped_keys(notice: Notice, scoped_keys: set[str]) -> bool:
    """Match newspaper-county ads by case or advert id after hydrate fills the case."""
    if notice.case_number and notice.case_number in scoped_keys:
        return True
    if notice.advert_id and notice.advert_id in scoped_keys:
        return True
    return False


def is_sacramento_cnpa_candidate(notice: Notice, scoped_keys: set[str]) -> bool:
    """Cheap pre-hydrate keep: scoped paper, court/case signal, or Sacramento in the card."""
    if in_sacramento_scoped_keys(notice, scoped_keys):
        return True
    if is_sacramento_court_notice(notice):
        return True
    blob = f"{notice.raw_text} {notice.snippet} {notice.newspaper} {notice.court_county}"
    if "SACRAMENTO" in blob.upper():
        return True
    return bool(extract_sacramento_case(blob))


def sacramento_cnpa_candidates(
    notices: list[Notice], scoped_keys: set[str]
) -> list[Notice]:
    return [notice for notice in notices if is_sacramento_cnpa_candidate(notice, scoped_keys)]


def keep_sacramento_notices(
    notices: list[Notice], scoped_keys: set[str]
) -> list[Notice]:
    kept: list[Notice] = []
    for notice in notices:
        if in_sacramento_scoped_keys(notice, scoped_keys) or is_sacramento_court_notice(
            notice
        ):
            kept.append(notice)
    return kept


def extract_sacramento_case(text: str) -> str:
    matches = SAC_CASE_RE.findall(text or "")
    if matches:
        year, number = matches[-1]
        return f"{year}PR{int(number):06d}"
    legacy = LEGACY_CASE_RE.findall(text or "")
    return legacy[-1] if legacy else ""


def advert_text(page_html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page_html, "html.parser")
    chunks = []
    for el in soup.select(".description, .panel-body"):
        text = el.get_text("\n", strip=True)
        fields = notice_fields(text, extract_sacramento_case)
        if fields.get("raw_text"):
            chunks.append(fields["raw_text"])
    if not chunks:
        return ""
    return max(chunks, key=len)


def needs_advert(notice: Notice) -> bool:
    raw = notice.raw_text or ""
    return bool(notice.advert_id) and (
        len(raw) < 500 or "IF YOU OBJECT" not in raw.upper() or not notice.case_number
    )


def hydrate_notice(notice: Notice) -> str:
    if not needs_advert(notice):
        return ""
    try:
        page = fetch_page(notice.notice_url)
    except requests.RequestException as exc:
        return f"CNPA list text was cut off and the advert page did not load ({exc})."
    full = advert_text(page)
    if len(full) <= len(notice.raw_text or ""):
        return "CNPA list text was cut off and the advert page had no longer notice."
    fields = notice_fields(full, extract_sacramento_case)
    if not fields:
        return "CNPA list text was cut off and the advert page had no longer notice."
    for key, value in fields.items():
        setattr(notice, key, value)
    return "Search card was shortened; full notice text was read from the CNPA advert page."


def _petition_docs_dir(out_dir: Path | None = None) -> Path:
    return petition_docs_dir("sacramento", out_dir=out_dir)


def enrich_notices(
    notices: list[Notice],
    docs_dir: Path | None = None,
    *,
    reuse_local: bool = True,
    refresh_cases: list[str] | None = None,
    listings_catalog: dict | None = None,
) -> list[dict]:
    try:
        from .datasources import (
            apply_stored_petitions,
            case_docs_folder,
            case_safe_name,
            is_valid_pdf,
            overlay_prior_listing,
            public_download_items,
            should_reuse_local_case,
        )
        from .sacramento_portal import SacramentoPortal
    except ImportError:
        from datasources import (
            apply_stored_petitions,
            case_docs_folder,
            case_safe_name,
            is_valid_pdf,
            overlay_prior_listing,
            public_download_items,
            should_reuse_local_case,
        )
        from sacramento_portal import SacramentoPortal

    client = None

    def _client() -> SacramentoPortal:
        nonlocal client
        if client is None:
            client = SacramentoPortal(pause=portal_pause_seconds())
        return client

    rows = []
    total = len(notices)
    catalog = listings_catalog or {}
    for index, notice in enumerate(notices, 1):
        reuse = should_reuse_local_case(
            docs_dir,
            notice.case_number,
            reuse_local=reuse_local,
            refresh_cases=refresh_cases,
        )
        _progress(
            "ecourt",
            (
                f"Reusing on-disk {notice.case_number} (skip court)"
                if reuse
                else f"Sacramento portal {index} of {total}: {notice.case_number or 'no case'}…"
            ),
            ecourt_total=total,
            ecourt_index=index,
        )
        portal: dict = {"found": False}
        if reuse:
            portal = {
                "found": True,
                "reused_local": True,
                "court_fetch": False,
                "case_number": notice.case_number,
            }
            overlay_prior_listing(portal, catalog.get(notice.case_number))
            print(f"Skipping court portal {notice.case_number}: complete local copy", flush=True)
        elif notice.case_number:
            try:
                portal = _client().enrich(notice.case_number)
            except requests.RequestException as exc:
                portal = {
                    "found": False,
                    "error": str(exc),
                    "case_number": notice.case_number,
                }
            portal["court_fetch"] = True
        if docs_dir and notice.case_number and not reuse:
            case_dir = case_docs_folder(docs_dir, notice.case_number)
            safe = case_safe_name(notice.case_number)
            skip_download = not _client().logged_in
            petition_item, duties_item = (None, None)
            if portal.get("found") and not skip_download:
                petition_item, duties_item = public_download_items(portal)
            dest111 = case_dir / f"{safe}_DE-111.pdf"
            dest147 = case_dir / f"{safe}_DE-147.pdf"
            if petition_item and petition_item.get("url") and not skip_download:
                try:
                    time.sleep(_client().pause)
                    _client().download(petition_item["url"], dest111)
                    portal["petition_url"] = petition_item["url"]
                except Exception as exc:  # noqa: BLE001
                    portal["petition_parse_error"] = str(exc)
                if dest111.is_file() and not is_valid_pdf(dest111):
                    portal["petition_parse_error"] = "download was not a PDF"
            if duties_item and duties_item.get("url") and not skip_download:
                try:
                    time.sleep(_client().pause)
                    _client().download(duties_item["url"], dest147)
                    portal["duties_url"] = duties_item["url"]
                except Exception as exc:  # noqa: BLE001
                    portal["duties_parse_error"] = str(exc)
                if dest147.is_file() and not is_valid_pdf(dest147):
                    portal["duties_parse_error"] = "download was not a PDF"
        if docs_dir and notice.case_number:
            apply_stored_petitions(
                portal,
                docs_dir=docs_dir,
                case_number=notice.case_number,
                petitioner=notice.petitioner,
                verbose=False,
            )
        row = asdict(notice)
        note = getattr(notice, "source_note", "") or getattr(notice, "extra_flag", "")
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
        row["source_id"] = "sacramento"
        row["court_fetch"] = bool(portal.get("court_fetch"))
        row["reused_local"] = bool(portal.get("reused_local"))
        if not row.get("filed"):
            row["filed"] = portal.get("filed") or portal.get("filed_from_docket")
        if note:
            row["extra_flag"] = note
        rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Sacramento probate notice digest")
    parser.add_argument("--lookback-days", type=int, default=21)
    parser.add_argument("--lookahead-days", type=int, default=21)
    parser.add_argument("--state-file", default="data/seen_cases_sacramento.json")
    parser.add_argument("--out-dir", default="data/reports/sacramento")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-portal", action="store_true")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--fub-verify-one", action="store_true")
    parser.add_argument("--fub-preview-one", action="store_true")
    parser.add_argument(
        "--rescan-local",
        action="store_true",
        help="Re-parse on-disk DE-111/DE-147 PDFs only; no CNPA search and no court portal",
    )
    parser.add_argument(
        "--test-stored",
        action="store_true",
        help="Parse on-disk PDFs and score the Go checklist. No CNPA, court, email, or Follow Up Boss",
    )
    parser.add_argument(
        "--refresh-case",
        action="append",
        default=[],
        help="Force a court portal fetch for this case even if a local copy exists",
    )
    parser.add_argument("--env-file", default=".env")
    return parser.parse_args()


def _run_rescan_local(args: argparse.Namespace, root: Path) -> int:
    state_path = Path(args.state_file)
    if not state_path.is_absolute():
        state_path = (root / args.state_file).resolve()
    else:
        state_path = state_path.resolve()
    state = load_state(state_path)
    os.environ.setdefault("PPM_PROGRESS_PATH", str(state_path.parent / "job_progress.json"))
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = root / args.out_dir
    docs_dir = _petition_docs_dir(out_dir)
    run_date = today_local().isoformat()
    listings_path = state_path.parent / "listings.json"
    sac_listings = state_path.parent / "listings_sacramento.json"
    catalog = _read_listings_catalog(listings_path)
    catalog.update(_read_listings_catalog(sac_listings))
    test_stored = bool(getattr(args, "test_stored", False))
    kind = "stored test" if test_stored else "local rescan"
    _progress(
        "rescan",
        f"Re-parsing on-disk Sacramento PDFs in {docs_dir} (no CNPA, no court)…",
    )
    rows = rescan_local_rows("sacramento", docs_dir, listings_catalog=catalog)
    rows = stamp_fub_tags(rows, COUNTY)
    if not test_stored:
        merge_listings(listings_path, rows, run_date)
        merge_listings(sac_listings, rows, run_date)
    print(
        f"Sacramento {kind} — {run_date} — 0 new / {len(rows)} unique",
        flush=True,
    )
    _progress(
        "cnpa_done",
        f"Local {kind} found {len(rows)} on-disk Sacramento cases.",
        notices=len(rows),
        notice_count=len(rows),
        new_count=0,
    )
    if test_stored:
        return _finish_stored_test(rows, state_path, source_id="sacramento")
    result = _finish_fub(args, rows, state, state_path, source_id="sacramento")
    if result == 0:
        return 0
    _progress("done", f"Sacramento local rescan finished. Cases {len(rows)}.")
    print(f"\nSaved state to {state_path}. Email skipped (local rescan).")
    return 0


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    root = Path(__file__).resolve().parent
    load_env_file(root / args.env_file)
    os.environ["FUB_DATA_SOURCE"] = "sacramento"
    os.environ["PROBATE_COUNTY"] = COUNTY
    os.environ["PROBATE_KEYWORDS"] = KEYWORDS
    if args.fub_preview_one:
        os.environ["FUB_PREVIEW_ONE"] = "1"
    if args.fub_verify_one:
        os.environ["FUB_VERIFY_ONLY"] = "1"
    if args.test_stored or args.rescan_local:
        return _run_rescan_local(args, root)

    start, end = default_window(args.lookback_days, args.lookahead_days)
    try:
        notices, urls, scoped_keys = collect_sacramento_cnpa_notices(start, end)
    except requests.RequestException as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 2

    unique = dedupe(notices)
    candidates = sacramento_cnpa_candidates(unique, scoped_keys)
    print(
        f"Opening full advert pages for {sum(1 for n in candidates if needs_advert(n))} shortened cards…",
        flush=True,
    )
    for notice in candidates:
        notice.source_note = hydrate_notice(notice)
        notice.extra_flag = notice.source_note
    unique = keep_sacramento_notices(candidates, scoped_keys)

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
        f"CNPA found {len(unique)} unique Sacramento notices ({new_count} new in this window).",
        notices=len(unique),
        notice_count=len(unique),
        new_count=new_count,
    )

    text_body = build_text(unique, start, end, urls, county=COUNTY)
    html_body = build_html(unique, start, end, urls, county=COUNTY)
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = root / args.out_dir
    write_outputs(out_dir, text_body, html_body, unique)

    stamp = datetime.now(get_tz()).strftime("%Y-%m-%d")
    pdf_path = out_dir / f"Sacramento-Probate-Daily-Feed-{stamp}.pdf"
    rows = [asdict(n) for n in unique]
    for row, notice in zip(rows, unique):
        note = getattr(notice, "source_note", "")
        if note:
            row["extra_flag"] = note
        row["source_id"] = "sacramento"
    if not args.skip_portal:
        print("Looking up each case on the Sacramento public portal…", flush=True)
        try:
            from .datasources import preview_refresh_case
        except ImportError:
            from datasources import preview_refresh_case

        docs_dir = _petition_docs_dir(out_dir)
        refresh_cases = [str(item).strip() for item in (args.refresh_case or []) if str(item).strip()]
        if args.fub_preview_one:
            pick = preview_refresh_case(unique, docs_dir)
            if pick and pick not in refresh_cases:
                refresh_cases.append(pick)
        catalog = _read_listings_catalog(state_path.parent / "listings.json")
        catalog.update(_read_listings_catalog(state_path.parent / "listings_sacramento.json"))
        rows = enrich_notices(
            unique,
            docs_dir=docs_dir,
            reuse_local=True,
            refresh_cases=refresh_cases,
            listings_catalog=catalog,
        )
        (out_dir / f"sacramento-dossiers-{stamp}.json").write_text(
            json.dumps(rows, indent=2), encoding="utf-8"
        )
    else:
        _progress("ecourt_skip", "Skipping Sacramento portal lookups.")
    rows = stamp_fub_tags(rows, COUNTY)
    merge_listings(state_path.parent / "listings.json", rows, run_date)
    merge_listings(state_path.parent / "listings_sacramento.json", rows, run_date)
    if not args.no_pdf:
        try:
            from .pdf_report import build_pdf
        except ImportError:
            from pdf_report import build_pdf

        _progress("pdf", "Building the Sacramento daily PDF…")
        build_pdf(
            rows,
            pdf_path,
            today_local(),
            start,
            end,
            county=COUNTY,
            source_note=SOURCE_NOTE,
            intro=INTRO,
        )
        print(f"Wrote PDF {pdf_path}")
    else:
        pdf_path = None

    new_count = sum(1 for n in unique if n.first_seen)
    subject = (
        f"Sacramento probate notices — {run_date} — "
        f"{new_count} new / {len(unique)} unique"
    )
    print(text_body)

    if args.fub_preview_one:
        try:
            from .fub_client import preview_one_record
        except ImportError:
            from fub_client import preview_one_record

        _progress("preview", "Previewing one Sacramento extract (not posting to Follow Up Boss)…")
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
                    "source_id": "sacramento",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("\nPreview only: Follow Up Boss not updated, seen-cases not updated.")
        _progress(
            "done",
            "Sacramento preview finished (Follow Up Boss not updated).",
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

    _progress("fub", "Importing Sacramento go-cases into Follow Up Boss…")
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
    text_body, html_body = refresh_digest_with_fub(
        unique,
        start,
        end,
        urls,
        out_dir,
        county=COUNTY,
        posted=posted,
        updated=updated,
        skipped=skipped,
    )
    subject = (
        f"Sacramento probate notices — {run_date} — "
        f"{new_count} new / {len(unique)} unique · FUB posted {posted}"
    )
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
                "source_id": "sacramento",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.no_email:
        print(f"\nSaved state to {state_path}. Email skipped.")
        _progress(
            "done",
            f"Sacramento job finished. FUB posted {posted}, updated {updated}, skipped {skipped}.",
            fub_posted=posted,
            fub_updated=updated,
            fub_skipped=skipped,
        )
        return 0
    _progress("email", "Sending the Sacramento daily email…")
    send_email(subject, text_body, html_body, pdf_path=pdf_path)
    print("\nEmail sent.")
    _progress(
        "done",
        f"Sacramento job finished. FUB posted {posted}, updated {updated}, skipped {skipped}.",
        fub_posted=posted,
        fub_updated=updated,
        fub_skipped=skipped,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
