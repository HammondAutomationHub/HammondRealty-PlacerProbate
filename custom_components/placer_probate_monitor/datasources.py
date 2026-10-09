#!/usr/bin/env python3
"""Probate lead datasource for the Home Assistant / Follow Up Boss app.

Both counties keep the existing Follow Up Boss tag ``probate``.
Sacramento adds ``sacramento`` beside it. Callers must merge tags
onto a person (Follow Up Boss ``mergeTags=true``). Sending tags
without that flag replaces the person's whole tag list.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

FUB_TAG_PROBATE = "probate"
FUB_TAG_SACRAMENTO = "sacramento"

COUNTY_FUB_TAGS = {
    "placer": [FUB_TAG_PROBATE],
    "sacramento": [FUB_TAG_PROBATE, FUB_TAG_SACRAMENTO],
}

COUNTY_FUB_LEAD_SOURCES = {
    "placer": "probate placer",
    "sacramento": "probate sacramento",
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
                COUNTY,
                KEYWORDS,
                enrich_notices,
                extract_sacramento_case,
                hydrate_notice,
                needs_advert,
            )
        except ImportError:
            from sacramento_probate_monitor import (
                COUNTY,
                KEYWORDS,
                enrich_notices,
                extract_sacramento_case,
                hydrate_notice,
                needs_advert,
            )

        notices, _urls = paginate(
            start,
            end,
            county=COUNTY,
            keywords=KEYWORDS,
            case_extractor=extract_sacramento_case,
        )
        unique = dedupe(notices)
        for notice in unique:
            if needs_advert(notice):
                notice.source_note = hydrate_notice(notice)
        if skip_portal:
            rows = [asdict(notice) for notice in unique]
            for row, notice in zip(rows, unique):
                note = getattr(notice, "source_note", "")
                if note:
                    row["extra_flag"] = note
        else:
            rows = enrich_notices(unique)
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
            rows = enrich_notices(unique, year=start.year)
        return stamp_fub_tags(rows, "Placer")
    raise ValueError(f"Unknown county {county!r}. Known: placer, sacramento")
