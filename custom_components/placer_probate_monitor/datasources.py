#!/usr/bin/env python3
"""Probate lead datasource for the Home Assistant / Follow Up Boss app.

Both counties keep the existing Follow Up Boss tag ``probate``.
Sacramento adds ``sacramento`` beside it. Callers must merge tags
onto a person (Follow Up Boss ``mergeTags=true``). Sending tags
without that flag replaces the person's whole tag list.
"""

from __future__ import annotations

from typing import Any

FUB_TAG_PROBATE = "probate"
FUB_TAG_SACRAMENTO = "sacramento"

COUNTY_FUB_TAGS = {
    "placer": [FUB_TAG_PROBATE],
    "sacramento": [FUB_TAG_PROBATE, FUB_TAG_SACRAMENTO],
}


def fub_tags(county: str) -> list[str]:
    key = county.strip().lower()
    try:
        return list(COUNTY_FUB_TAGS[key])
    except KeyError as exc:
        known = ", ".join(sorted(COUNTY_FUB_TAGS))
        raise ValueError(f"Unknown county {county!r}. Known: {known}") from exc


def stamp_fub_tags(rows: list[dict], county: str) -> list[dict]:
    tags = fub_tags(county)
    key = county.strip().lower()
    for row in rows:
        row["tags"] = list(tags)
        row["source_id"] = key if key in COUNTY_FUB_TAGS else county
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
