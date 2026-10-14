#!/usr/bin/env python3
"""Copy recent Placer Probate Monitor logs from Home Assistant onto this laptop.

Uses a long-lived access token (Profile → Security → Long-lived access tokens).
Writes into ``data/ha_logs/`` (gitignored) so Cursor can review job output
without scraping ``home-assistant.log``.

    python scripts/pull_ha_logs.py --url https://homeassistant.local:8123 --token TOKEN

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

from ha_logs import (  # noqa: E402
    HA_LOGS_URL,
    write_ha_logs_locally,
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
            "User-Agent": "HammondRealty-PlacerProbate/pull_ha_logs",
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


def pull_logs(
    ha_url: str,
    token: str,
    dest: Path,
    source_id: str | None,
    *,
    insecure: bool,
) -> list[str]:
    query: dict[str, str] = {}
    if source_id:
        query["source_id"] = source_id
    path = HA_LOGS_URL
    if query:
        path = f"{path}?{urllib.parse.urlencode(query)}"
    payload = json.loads(
        _request(_base(ha_url) + path, token, insecure=insecure).decode("utf-8")
    )
    if not isinstance(payload, dict) or not payload.get("ok"):
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("error") or "")
        raise SystemExit(message or "Home Assistant did not return logs.")
    return write_ha_logs_locally(payload, dest)


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
        help="County job section to pull (default: both)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "ha_logs",
        help="Laptop directory for pulled logs",
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
    written = pull_logs(
        args.url,
        args.token,
        args.out,
        source_id,
        insecure=args.insecure,
    )
    print(f"Wrote {len(written)} file(s) under {args.out}")
    for name in written:
        print(f"  {name}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
