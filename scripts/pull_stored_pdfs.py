#!/usr/bin/env python3
"""Copy stored petition PDFs from Home Assistant onto this laptop.

Uses a long-lived access token (Profile → Security → Long-lived access tokens).
Default layout matches the integration: extract into the repo ``data/`` folder
so parsers read ``data/reports/docs`` and ``data/reports/sacramento/docs``.

    python scripts/pull_stored_pdfs.py --url https://homeassistant.local:8123 --token TOKEN

Environment: HA_URL / HASS_URL and HA_TOKEN / HASS_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from datasources import (  # noqa: E402
    safe_extract_stored_zip,
    STORED_DOCS_FILE_URL,
    STORED_DOCS_ZIP_URL,
)


def _base(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def _request(
    url: str,
    token: str,
    *,
    insecure: bool = False,
    accept: str = "application/json",
) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "User-Agent": "HammondRealty-PlacerProbate/pull_stored_pdfs",
        },
        method="GET",
    )
    context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=context, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = str(body.get("message") or body.get("error") or "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise SystemExit(
            f"HTTP {exc.code} from {url.split('?', 1)[0]}"
            + (f": {detail}" if detail else "")
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Home Assistant: {exc.reason}") from exc


def pull_zip(ha_url: str, token: str, dest: Path, source_id: str | None, *, insecure: bool) -> list[str]:
    path = STORED_DOCS_ZIP_URL
    if source_id:
        path = f"{path}?source_id={urllib.parse.quote(source_id)}"
    blob = _request(_base(ha_url) + path, token, insecure=insecure, accept="application/zip")
    return safe_extract_stored_zip(blob, dest)


def pull_files(
    ha_url: str,
    token: str,
    dest: Path,
    source_id: str | None,
    *,
    insecure: bool,
    skip_existing: bool,
) -> list[str]:
    qs = f"?source_id={urllib.parse.quote(source_id)}" if source_id else ""
    payload = json.loads(
        _request(
            _base(ha_url) + "/api/placer_probate_monitor/stored_docs" + qs,
            token,
            insecure=insecure,
        ).decode("utf-8")
    )
    written: list[str] = []
    dest = Path(dest)
    for county in payload.get("counties") or []:
        relative = str(county.get("relative_dir") or "").replace("\\", "/").strip("/")
        cid = str(county.get("id") or "")
        if not relative or cid not in {"placer", "sacramento"}:
            continue
        for case in county.get("cases") or []:
            case_number = str(case.get("case_number") or "").strip()
            for name in case.get("files") or []:
                filename = Path(str(name)).name
                if filename != str(name):
                    continue
                member = f"{relative}/{case_number}/{filename}"
                target = dest / member
                if skip_existing and target.is_file():
                    continue
                query = urllib.parse.urlencode(
                    {"source_id": cid, "case": case_number, "name": filename}
                )
                blob = _request(
                    _base(ha_url) + f"{STORED_DOCS_FILE_URL}?{query}",
                    token,
                    insecure=insecure,
                    accept="application/pdf",
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
                written.append(member)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("HA_URL") or os.environ.get("HASS_URL") or "",
        help="Home Assistant base URL, e.g. https://homeassistant.local:8123",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HA_TOKEN") or os.environ.get("HASS_TOKEN") or "",
        help="Long-lived access token",
    )
    parser.add_argument(
        "--source",
        choices=["all", "placer", "sacramento"],
        default="all",
        help="County to pull (default: both)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data",
        help="Laptop data directory (zip members start at reports/)",
    )
    parser.add_argument(
        "--files",
        action="store_true",
        help="Download each PDF instead of one zip (supports --skip-existing)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="With --files, skip PDFs that already exist locally",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification",
    )
    args = parser.parse_args(argv)
    if not args.url or not args.token:
        parser.error("Need --url and --token (or HA_URL and HA_TOKEN).")
    source_id = None if args.source == "all" else args.source
    dest = args.out
    if args.files:
        written = pull_files(
            args.url,
            args.token,
            dest,
            source_id,
            insecure=args.insecure,
            skip_existing=args.skip_existing,
        )
    else:
        written = pull_zip(args.url, args.token, dest, source_id, insecure=args.insecure)
    print(f"Wrote {len(written)} PDF(s) under {dest}")
    for name in written[:20]:
        print(f"  {name}")
    if len(written) > 20:
        print(f"  … {len(written) - 20} more")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
