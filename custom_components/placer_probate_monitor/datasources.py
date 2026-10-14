#!/usr/bin/env python3
"""Probate lead datasource for the Home Assistant / Follow Up Boss app.

Every county uses Follow Up Boss lead source ``probate`` and tags
``probate`` plus the county name. Callers must merge tags onto a
person (Follow Up Boss ``mergeTags=true``). Sending tags without
that flag replaces the person's whole tag list.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

FUB_TAG_PROBATE = "probate"
FUB_LEAD_SOURCE = "probate"

COUNTY_FUB_TAGS = {
    "placer": [FUB_TAG_PROBATE, "placer"],
    "sacramento": [FUB_TAG_PROBATE, "sacramento"],
}

COUNTY_FUB_LEAD_SOURCES = {
    "placer": FUB_LEAD_SOURCE,
    "sacramento": FUB_LEAD_SOURCE,
}


def fub_tags(county: str) -> list[str]:
    key = county.strip().lower()
    try:
        return list(COUNTY_FUB_TAGS[key])
    except KeyError as exc:
        known = ", ".join(sorted(COUNTY_FUB_TAGS))
        raise ValueError(f"Unknown county {county!r}. Known: {known}") from exc


def fub_lead_source(county: str) -> str:
    key = county.strip().lower()
    try:
        return COUNTY_FUB_LEAD_SOURCES[key]
    except KeyError as exc:
        known = ", ".join(sorted(COUNTY_FUB_LEAD_SOURCES))
        raise ValueError(f"Unknown county {county!r}. Known: {known}") from exc


def petition_docs_dir(
    source_id: str | None = None,
    *,
    out_dir: Path | None = None,
    data_dir: Path | None = None,
) -> Path:
    """Directory for downloaded DE-111 / DE-147 PDFs for one county.

    Placer stays at ``reports/docs``. Sacramento is
    ``reports/sacramento/docs`` so HMAC URLs can still look up either folder.
    """
    key = (
        str(source_id or os.environ.get("FUB_DATA_SOURCE") or "placer")
        .strip()
        .lower()
        or "placer"
    )
    if key == "sacramento":
        env = str(os.environ.get("FUB_SACRAMENTO_PETITION_DOCS_DIR") or "").strip()
        if env:
            return Path(env)
        if out_dir is not None:
            return Path(out_dir) / "docs"
        if data_dir is not None:
            return Path(data_dir) / "reports" / "sacramento" / "docs"
        placer_env = str(os.environ.get("FUB_PETITION_DOCS_DIR") or "").strip()
        if placer_env:
            base = Path(placer_env)
            if base.name == "docs":
                return base.parent / "sacramento" / "docs"
            return base / "sacramento" / "docs"
        return Path("data/reports/sacramento/docs")
    env = str(os.environ.get("FUB_PETITION_DOCS_DIR") or "").strip()
    if env:
        return Path(env)
    if out_dir is not None:
        return Path(out_dir) / "docs"
    if data_dir is not None:
        return Path(data_dir) / "reports" / "docs"
    return Path("data/reports/docs")


PDF_MAGIC = b"%PDF"
_SAFE_CASE_RE = re.compile(r"[^\w\-]+")


def case_safe_name(case_number: str) -> str:
    return _SAFE_CASE_RE.sub("_", (case_number or "").strip())


def is_valid_pdf(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        if not path.is_file() or path.stat().st_size <= 4:
            return False
        with path.open("rb") as handle:
            return handle.read(4) == PDF_MAGIC
    except OSError:
        return False


def _compact_doc_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def is_de147s_name(name: str) -> bool:
    return "de147s" in _compact_doc_name(name)


def is_de147_name(name: str) -> bool:
    if is_de147s_name(name):
        return False
    return "de147" in _compact_doc_name(name)


def is_de111_name(name: str) -> bool:
    if is_de147s_name(name) or is_de147_name(name):
        return False
    return "de111" in _compact_doc_name(name)


def case_docs_folder(docs_dir: Path, case_number: str) -> Path:
    return Path(docs_dir) / case_safe_name(case_number)


def _iter_case_pdfs(docs_dir: Path, case_number: str) -> list[Path]:
    safe = case_safe_name(case_number)
    if not safe:
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for folder in (Path(docs_dir) / safe, Path(docs_dir)):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.pdf")):
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def local_de111_pdf(docs_dir: Path | None, case_number: str) -> Path | None:
    """Valid on-disk DE-111, or any other public petition PDF in the case folder."""
    if docs_dir is None or not str(case_number or "").strip():
        return None
    base = Path(docs_dir)
    safe = case_safe_name(case_number)
    for path in (
        base / safe / f"{safe}_DE-111.pdf",
        base / f"{safe}_DE-111.pdf",
    ):
        if is_valid_pdf(path) and not is_de147s_name(path.name):
            return path
    fallback = None
    for path in _iter_case_pdfs(base, case_number):
        if not is_valid_pdf(path) or is_de147s_name(path.name) or is_de147_name(path.name):
            continue
        if is_de111_name(path.name):
            return path
        if fallback is None:
            fallback = path
    return fallback


def local_de147_pdf(docs_dir: Path | None, case_number: str) -> Path | None:
    if docs_dir is None or not str(case_number or "").strip():
        return None
    base = Path(docs_dir)
    safe = case_safe_name(case_number)
    for path in (
        base / safe / f"{safe}_DE-147.pdf",
        base / f"{safe}_DE-147.pdf",
    ):
        if is_valid_pdf(path) and not is_de147s_name(path.name):
            return path
    for path in _iter_case_pdfs(base, case_number):
        if is_valid_pdf(path) and is_de147_name(path.name):
            return path
    return None


def local_case_complete(
    docs_dir: Path | None,
    case_number: str,
    *,
    require_duties: bool = False,
) -> bool:
    """True when we already have the petition materials needed to parse/FUB.

    A valid DE-111 (or another public petition PDF in the case folder / docs
    root) is enough. DE-147 is optional unless ``require_duties`` is set.
    Empty folders, non-PDFs, login failures, and Not Viewable-only results
    are incomplete. Confidential DE-147S files never count.
    """
    petition = local_de111_pdf(docs_dir, case_number)
    if petition is None:
        return False
    if require_duties:
        return local_de147_pdf(docs_dir, case_number) is not None
    return True


def should_reuse_local_case(
    docs_dir: Path | None,
    case_number: str,
    *,
    reuse_local: bool = True,
    refresh_cases: Iterable[str] | None = None,
) -> bool:
    if not reuse_local or docs_dir is None or not str(case_number or "").strip():
        return False
    refresh = {str(item).strip() for item in (refresh_cases or []) if str(item).strip()}
    if str(case_number).strip() in refresh:
        return False
    return local_case_complete(docs_dir, case_number)


def preview_refresh_case(
    notices: Iterable[Any],
    docs_dir: Path | None,
) -> str:
    """One case for Preview: prefer incomplete local files, else the first case."""
    numbered = [str(getattr(item, "case_number", "") or "").strip() for item in notices]
    numbered = [item for item in numbered if item]
    incomplete = [
        case for case in numbered if not local_case_complete(docs_dir, case)
    ]
    if incomplete:
        return incomplete[0]
    return numbered[0] if numbered else ""


def overlay_prior_listing(portal: dict, listing: dict | None) -> dict:
    if not listing:
        return portal
    mapping = (
        ("court_url", "court_url"),
        ("filed", "filed"),
        ("decedent", "decedent"),
        ("petitioner", "petitioner"),
        ("decedent_address", "decedent_residence"),
        ("petitioner_address", "mailing_address"),
        ("hearing", "next_event"),
        ("notice_url", "notice_url"),
    )
    for src, dest in mapping:
        value = listing.get(src)
        if value not in (None, "", [], {}) and not portal.get(dest):
            portal[dest] = value
    return portal


def apply_stored_petitions(
    portal: dict,
    *,
    docs_dir: Path,
    case_number: str,
    petitioner: str = "",
    verbose: bool = False,
) -> dict:
    """Parse on-disk DE-111 / public DE-147 into portal fields. No download."""
    try:
        from .petition_parse import (
            contact_fields,
            merge_petitioner_contact,
            parse_de111_pdf,
            parse_de147_pdf,
        )
    except ImportError:
        from petition_parse import (
            contact_fields,
            merge_petitioner_contact,
            parse_de111_pdf,
            parse_de147_pdf,
        )

    de111: dict = {}
    de147: dict = {}
    dest111 = local_de111_pdf(docs_dir, case_number)
    dest147 = local_de147_pdf(docs_dir, case_number)
    if dest111 is not None:
        try:
            de111 = parse_de111_pdf(dest111, petitioner=petitioner)
            if de111.get("petitioner_name"):
                portal["petitioner"] = de111["petitioner_name"]
            if de111.get("decedent_name") and not portal.get("decedent"):
                portal["decedent"] = de111["decedent_name"]
            portal.update(de111)
            portal["petition_pdf"] = str(dest111)
            if verbose:
                print(
                    f"DE-111 {case_number}: "
                    f"mailing={de111.get('mailing_address') or '(empty)'} "
                    f"phone={de111.get('petitioner_phone') or '(empty)'} "
                    f"residence={de111.get('decedent_residence') or '(empty)'}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            portal["petition_parse_error"] = str(exc)
    if dest147 is not None:
        try:
            de147 = parse_de147_pdf(dest147)
            portal["duties_pdf"] = str(dest147)
            if verbose:
                print(
                    f"DE-147 {case_number}: "
                    f"mailing={de147.get('mailing_address') or '(empty)'} "
                    f"phone={de147.get('petitioner_phone') or '(empty)'} "
                    f"email={de147.get('petitioner_email') or '(empty)'}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            portal["duties_parse_error"] = str(exc)
    portal["contact_de111"] = contact_fields(de111)
    portal["contact_de147"] = contact_fields(de147)
    contact = merge_petitioner_contact(de111, de147)
    if contact:
        portal.update(contact)
        if verbose:
            print(
                f"contact {case_number}: "
                f"mailing={contact.get('mailing_address') or '(empty)'} "
                f"phone={contact.get('petitioner_phone') or '(empty)'} "
                f"email={contact.get('petitioner_email') or '(empty)'}",
                flush=True,
            )
    return portal


def public_download_items(portal: dict) -> tuple[dict | None, dict | None]:
    """First public petition and duties files. Never DE-147S / confidential."""
    try:
        from .petition_parse import looks_like_duties_form, looks_like_probate_petition
    except ImportError:
        from petition_parse import looks_like_duties_form, looks_like_probate_petition

    petition_item = None
    duties_item = None
    for item in portal.get("document_files") or []:
        if not item.get("available") or not item.get("url"):
            continue
        name = str(item.get("name") or "")
        if is_de147s_name(name) or "confidential" in name.lower():
            continue
        if looks_like_probate_petition(name) and petition_item is None:
            petition_item = item
        if looks_like_duties_form(name) and duties_item is None:
            duties_item = item
    return petition_item, duties_item


def _case_from_pdf_name(name: str) -> str:
    stem = Path(name).stem
    upper = stem.upper()
    for token in ("_DE-111", "_DE-147", "_DE111", "_DE147"):
        idx = upper.find(token)
        if idx > 0:
            return stem[:idx]
    return stem


def iter_local_case_numbers(docs_dir: Path | None) -> list[str]:
    """Case numbers that already have a public petition or duties PDF on disk."""
    if docs_dir is None:
        return []
    base = Path(docs_dir)
    if not base.is_dir():
        return []
    cases: set[str] = set()
    for child in base.iterdir():
        if child.name.startswith("."):
            continue
        if child.is_dir():
            name = child.name.strip()
            if name:
                cases.add(name)
            continue
        if child.suffix.lower() != ".pdf" or is_de147s_name(child.name):
            continue
        case = _case_from_pdf_name(child.name).strip()
        if case:
            cases.add(case)
    return sorted(
        case
        for case in cases
        if local_de111_pdf(base, case) or local_de147_pdf(base, case)
    )


def listed_case_pdfs(docs_dir: Path | None, case_number: str) -> list[str]:
    """Public on-disk PDF filenames for one case. Skips DE-147S / invalid files."""
    names: list[str] = []
    seen: set[str] = set()
    for path in _iter_case_pdfs(docs_dir or Path(), case_number):
        if not is_valid_pdf(path) or is_de147s_name(path.name):
            continue
        if path.name in seen:
            continue
        seen.add(path.name)
        names.append(path.name)
    return names


def stored_docs_inventory(docs_dir: Path | None, source_id: str, *, relative_dir: str) -> dict:
    """Case/PDF inventory for one county docs folder. No court or CNPA."""
    cases: list[dict[str, Any]] = []
    pdf_count = 0
    for case in iter_local_case_numbers(docs_dir):
        files = listed_case_pdfs(docs_dir, case)
        pdf_count += len(files)
        cases.append(
            {
                "case_number": case,
                "files": files,
                "has_de111": local_de111_pdf(docs_dir, case) is not None,
                "has_de147": local_de147_pdf(docs_dir, case) is not None,
            }
        )
    return {
        "id": str(source_id or "").strip().lower() or "placer",
        "relative_dir": relative_dir,
        "ha_path": f"config/placer_probate_monitor/{relative_dir}",
        "laptop_path": f"data/{relative_dir}",
        "case_count": len(cases),
        "pdf_count": pdf_count,
        "cases": cases,
    }


def all_stored_docs_inventory(data_dir: Path) -> dict:
    """All downloaded petition PDFs already on this Home Assistant box."""
    root = Path(data_dir)
    counties = [
        stored_docs_inventory(
            petition_docs_dir("placer", data_dir=root),
            "placer",
            relative_dir="reports/docs",
        ),
        stored_docs_inventory(
            petition_docs_dir("sacramento", data_dir=root),
            "sacramento",
            relative_dir="reports/sacramento/docs",
        ),
    ]
    return {
        "ha_root": "config/placer_probate_monitor",
        "copy_hint": (
            "These PDFs are already on Home Assistant under "
            "config/placer_probate_monitor/. Copy reports/docs and "
            "reports/sacramento/docs into a laptop checkout at data/reports/ "
            "to run parsers there. Test stored data on this box reads the same "
            "files in place and does not scrape CNPA or court portals."
        ),
        "counties": counties,
        "case_count": sum(int(item.get("case_count") or 0) for item in counties),
        "pdf_count": sum(int(item.get("pdf_count") or 0) for item in counties),
    }


def rescan_local_rows(
    source_id: str,
    docs_dir: Path | None,
    listings_catalog: dict[str, dict] | None = None,
) -> list[dict]:
    """Re-parse on-disk PDFs into dossier rows. Does not call CNPA or court."""
    catalog = listings_catalog or {}
    rows: list[dict] = []
    if docs_dir is None:
        return rows
    for case in iter_local_case_numbers(docs_dir):
        listing = catalog.get(case) or {}
        portal: dict[str, Any] = {
            "found": True,
            "reused_local": True,
            "rescanned_local": True,
            "court_fetch": False,
            "case_number": case,
        }
        overlay_prior_listing(portal, listing)
        apply_stored_petitions(
            portal,
            docs_dir=Path(docs_dir),
            case_number=case,
            petitioner=str(listing.get("petitioner") or portal.get("petitioner") or ""),
            verbose=True,
        )
        row: dict[str, Any] = {
            "case_number": case,
            "advert_id": "",
            "decedent": listing.get("decedent") or "",
            "petitioner": listing.get("petitioner") or "",
            "court_county": "Sacramento" if source_id == "sacramento" else "Placer",
            "hearing": listing.get("hearing") or "",
            "attorney": "",
            "attorney_phone": "",
            "newspaper": listing.get("newspaper") or "",
            "post_date": listing.get("date") or "",
            "publication_line": "",
            "will_offered": False,
            "iaea_requested": False,
            "refcode": "",
            "notice_url": listing.get("notice_url") or "",
            "snippet": "",
            "raw_text": "",
            "source_id": source_id,
            "first_seen": False,
            "status": "repeat",
        }
        merged = {key: value for key, value in portal.items() if value not in (None, "", [], {})}
        if "status" in merged and "court_status" not in merged:
            merged["court_status"] = merged.pop("status")
        else:
            merged.pop("status", None)
        row.update(merged)
        row["status"] = "repeat"
        row["first_seen"] = False
        row["found"] = True
        row["court_fetch"] = False
        row["rescanned_local"] = True
        row["reused_local"] = True
        if not row.get("filed"):
            row["filed"] = portal.get("filed") or listing.get("filed") or ""
        rows.append(row)
        print(f"Local rescan {case}: court skipped", flush=True)
    return rows


def stamp_fub_tags(rows: list[dict], county: str) -> list[dict]:
    tags = fub_tags(county)
    key = county.strip().lower()
    lead_source = fub_lead_source(key) if key in COUNTY_FUB_LEAD_SOURCES else ""
    for row in rows:
        row["tags"] = list(tags)
        row["source_id"] = key if key in COUNTY_FUB_TAGS else county
        if lead_source:
            row["lead_source"] = lead_source
    return rows


def collect_leads(
    county: str,
    *,
    lookback_days: int = 21,
    lookahead_days: int = 21,
    skip_portal: bool = False,
) -> list[dict[str, Any]]:
    """Return dossier rows for one county. Does not email or update seen-cases."""
    try:
        from .placer_probate_monitor import dedupe, default_window, paginate
    except ImportError:
        from placer_probate_monitor import dedupe, default_window, paginate

    key = county.strip().lower()
    start, end = default_window(lookback_days, lookahead_days)
    if key == "sacramento":
        from dataclasses import asdict

        try:
            from .sacramento_probate_monitor import (
                collect_sacramento_cnpa_notices,
                enrich_notices,
                hydrate_notice,
                keep_sacramento_notices,
                needs_advert,
            )
        except ImportError:
            from sacramento_probate_monitor import (
                collect_sacramento_cnpa_notices,
                enrich_notices,
                hydrate_notice,
                keep_sacramento_notices,
                needs_advert,
            )

        notices, _urls, scoped_keys = collect_sacramento_cnpa_notices(start, end)
        unique = dedupe(notices)
        candidates = [
            notice
            for notice in unique
            if (notice.case_number or notice.advert_id) in scoped_keys
            or "SACRAMENTO"
            in f"{notice.raw_text} {notice.snippet} {notice.newspaper} {notice.court_county}".upper()
        ]
        for notice in candidates:
            if needs_advert(notice):
                notice.source_note = hydrate_notice(notice)
        unique = keep_sacramento_notices(candidates, scoped_keys)
        if skip_portal:
            rows = [asdict(notice) for notice in unique]
            for row, notice in zip(rows, unique):
                note = getattr(notice, "source_note", "")
                if note:
                    row["extra_flag"] = note
        else:
            rows = enrich_notices(
                unique,
                docs_dir=petition_docs_dir("sacramento"),
                reuse_local=True,
            )
        return stamp_fub_tags(rows, "Sacramento")
    if key == "placer":
        from dataclasses import asdict

        try:
            from .placer_probate_monitor import enrich_notices
        except ImportError:
            from placer_probate_monitor import enrich_notices

        notices, _urls = paginate(start, end)
        unique = dedupe(notices)
        if skip_portal:
            rows = [asdict(notice) for notice in unique]
        else:
            rows = enrich_notices(
                unique,
                year=start.year,
                docs_dir=petition_docs_dir("placer"),
                reuse_local=True,
            )
        return stamp_fub_tags(rows, "Placer")
    raise ValueError(f"Unknown county {county!r}. Known: placer, sacramento")
