"""Live job progress for the Home Assistant panel."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def progress_path() -> Path | None:
    raw = str(os.environ.get("PPM_PROGRESS_PATH") or "").strip()
    return Path(raw) if raw else None


def read_progress(path: Path | None = None) -> dict:
    target = path or progress_path()
    if not target or not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def clear_progress() -> None:
    target = progress_path()
    if not target:
        return
    try:
        target.write_text(
            json.dumps(
                {
                    "step": "start",
                    "message": "Starting Placer job…",
                    "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def report_progress(step: str, message: str, **extra) -> None:
    payload = read_progress()
    payload.update(extra)
    payload["step"] = step
    payload["message"] = message
    payload["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"PROGRESS {message}", flush=True)
    target = progress_path()
    if not target:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
