"""Bounded on-disk job logs for the Home Assistant integration.

Job stdout already lands in ``last_run.log``. This module keeps a rotating
history, redacts secrets, and builds the authenticated ``/logs`` payload so
Cursor can pull files the same way it pulls stored PDFs.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HA_LOGS_URL = "/api/placer_probate_monitor/logs"
HA_LOGS_VIEW_NAME = "api:placer_probate_monitor:logs"
HA_LOGS_REQUIRES_AUTH = True

LAST_RUN_NAME = "last_run.log"
JOB_LOG_NAME = "job.log"
COMPONENT_LOG_NAME = "component.log"
SUMMARY_NAME = "summary.json"
PROGRESS_NAME = "job_progress.json"

LOGS_SUBDIR = "logs"
HA_PATH_HINT = "config/placer_probate_monitor"
LAPTOP_PATH_HINT = "data/ha_logs"

DEFAULT_EXPORT_MAX_BYTES = 256 * 1024
ABS_EXPORT_MAX_BYTES = 1024 * 1024
MIN_EXPORT_MAX_BYTES = 4096
ON_DISK_MAX_BYTES = 512 * 1024
SUMMARY_ERROR_LIMIT = 20
HANDLER_NAME = "placer_probate_monitor_file"

_SECTION = re.compile(r"^===== (\w+) =====\s*$", re.M)
_SECRET_ASSIGN = re.compile(
    r"(?i)((?:[A-Z0-9_]*_)?(?:"
    r"password|passwd|smtp_password|portal_password|"
    r"api[_-]?key|system[_-]?key|secret|token|access_token|"
    r"authorization|bearer|ha_token|hass_token"
    r"))(\s*[=:]\s*)([^\s\"'&,;]+)"
)
_BEARER = re.compile(r"(?i)(\bBearer\s+)(\S+)")
_BASIC = re.compile(r"(?i)(\bBasic\s+)(\S+)")

ALLOWED_EXPORT_FILES = frozenset(
    {LAST_RUN_NAME, JOB_LOG_NAME, COMPONENT_LOG_NAME, PROGRESS_NAME}
)


def logs_dir(data_dir: Path) -> Path:
    return Path(data_dir) / LOGS_SUBDIR


def job_log_path(data_dir: Path) -> Path:
    return logs_dir(data_dir) / JOB_LOG_NAME


def component_log_path(data_dir: Path) -> Path:
    return logs_dir(data_dir) / COMPONENT_LOG_NAME


def summary_path(data_dir: Path) -> Path:
    return logs_dir(data_dir) / SUMMARY_NAME


def clamp_max_bytes(value: Any, default: int = DEFAULT_EXPORT_MAX_BYTES) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(MIN_EXPORT_MAX_BYTES, min(n, ABS_EXPORT_MAX_BYTES))


def redact_secrets(text: str) -> str:
    """Strip tokens and passwords; leave the rest of the job log readable."""
    if not text:
        return ""
    out = _BEARER.sub(r"\1[REDACTED]", text)
    out = _BASIC.sub(r"\1[REDACTED]", out)
    out = _SECRET_ASSIGN.sub(r"\1\2[REDACTED]", out)
    return out


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def tail_text(text: str, max_bytes: int) -> tuple[str, bool]:
    raw = (text or "").encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text or "", False
    sliced = raw[-max_bytes:].decode("utf-8", errors="ignore")
    return sliced, True


def write_capped_text(path: Path, text: str, max_bytes: int = ON_DISK_MAX_BYTES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kept, _truncated = tail_text(text, max_bytes)
    path.write_text(kept, encoding="utf-8")


def append_bounded_text(
    path: Path, chunk: str, *, max_bytes: int = ON_DISK_MAX_BYTES
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""
    write_capped_text(path, existing + chunk, max_bytes)


def filter_log_source(text: str, source_id: str | None) -> str:
    wanted = str(source_id or "").strip().lower()
    if wanted not in {"placer", "sacramento"}:
        return text
    matches = list(_SECTION.finditer(text or ""))
    if not matches:
        return text
    chunks: list[str] = []
    for index, match in enumerate(matches):
        if match.group(1).lower() != wanted:
            continue
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunks.append((text[start:end]).rstrip() + "\n")
    return "".join(chunks).strip()


def read_json_object(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def merge_last_run_log(data_dir: Path, source_id: str, log_text: str) -> None:
    last_log = Path(data_dir) / LAST_RUN_NAME
    existing = ""
    if last_log.is_file():
        try:
            existing = last_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""
    prefix = f"\n===== {source_id} =====\n"
    write_capped_text(
        last_log,
        redact_secrets((existing + prefix + (log_text or "")).strip()),
        ON_DISK_MAX_BYTES,
    )


def persist_job_logs(
    data_dir: Path,
    *,
    source_id: str,
    log_text: str,
    ok: bool,
    error: str | None = None,
    job_id: str | None = None,
) -> dict:
    """Append this source's job output to the rotating history + JSON summary."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job = job_id or f"{now.replace(':', '').replace('-', '')}-{source_id}"
    header = f"\n===== {source_id} {now} job_id={job} ok={str(ok).lower()} =====\n"
    body = redact_secrets(log_text or "")
    append_bounded_text(job_log_path(data_dir), header + body + "\n")
    summary = read_json_object(summary_path(data_dir))
    errors = list(summary.get("errors") or [])
    err_text = redact_secrets(str(error or "").strip())
    if not ok and err_text:
        errors.append(
            {
                "job_id": job,
                "source_id": source_id,
                "at": now,
                "error": err_text[-500:],
            }
        )
        errors = errors[-SUMMARY_ERROR_LIMIT:]
    summary.update(
        {
            "last_job_id": job,
            "last_source": source_id,
            "last_ok": bool(ok),
            "last_error": err_text[-500:] if err_text else None,
            "last_finished": now,
            "updated": now,
            "errors": errors,
        }
    )
    write_capped_text(
        summary_path(data_dir),
        json.dumps(summary, indent=2),
        ON_DISK_MAX_BYTES,
    )
    return summary


class BoundedLogHandler(logging.Handler):
    """Write logger records into a size-capped file (no HA core log scrape)."""

    def __init__(self, path: Path, max_bytes: int = ON_DISK_MAX_BYTES) -> None:
        super().__init__()
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.set_name(HANDLER_NAME)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = redact_secrets(self.format(record)) + "\n"
            append_bounded_text(self.path, line, max_bytes=self.max_bytes)
        except Exception:  # noqa: BLE001
            self.handleError(record)


def attach_component_logger(data_dir: Path) -> None:
    path = component_log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = BoundedLogHandler(path)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    for name in (
        "custom_components.placer_probate_monitor",
        "placer_probate_monitor",
    ):
        logger = logging.getLogger(name)
        if any(getattr(item, "name", "") == HANDLER_NAME for item in logger.handlers):
            continue
        logger.addHandler(handler)


def _file_entry(name: str, text: str, max_bytes: int) -> dict:
    original = text or ""
    redacted = redact_secrets(original)
    clipped, truncated = tail_text(redacted, max_bytes)
    return {
        "name": name,
        "bytes": len(redacted.encode("utf-8")),
        "truncated": truncated,
        "text": clipped,
    }


def build_ha_logs_payload(
    data_dir: Path,
    source_id: str | None = None,
    max_bytes: Any = None,
) -> dict:
    """JSON for GET /api/placer_probate_monitor/logs. Secrets redacted, size capped."""
    root = Path(data_dir)
    cap = clamp_max_bytes(max_bytes)
    wanted = str(source_id or "").strip().lower() or None
    last_run = ""
    last_path = root / LAST_RUN_NAME
    if last_path.is_file():
        try:
            last_run = last_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            last_run = ""
    last_run = filter_log_source(last_run, wanted)
    files = [_file_entry(LAST_RUN_NAME, last_run, cap)]
    for name, path in (
        (JOB_LOG_NAME, job_log_path(root)),
        (COMPONENT_LOG_NAME, component_log_path(root)),
    ):
        text = ""
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
        files.append(_file_entry(name, text, cap))
    summary = redact_value(read_json_object(summary_path(root)))
    progress = redact_value(read_json_object(root / PROGRESS_NAME))
    return {
        "ok": True,
        "ha_path": HA_PATH_HINT,
        "laptop_path": LAPTOP_PATH_HINT,
        "source_id": wanted,
        "max_bytes": cap,
        "summary": summary,
        "progress": progress,
        "files": files,
        "download": HA_LOGS_URL,
    }


def write_ha_logs_locally(payload: dict, dest: Path) -> list[str]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    envelope = {key: value for key, value in payload.items() if key != "files"}
    (dest / SUMMARY_NAME).write_text(
        json.dumps(envelope, indent=2), encoding="utf-8"
    )
    written.append(SUMMARY_NAME)
    progress = payload.get("progress")
    if isinstance(progress, dict):
        (dest / PROGRESS_NAME).write_text(
            json.dumps(progress, indent=2), encoding="utf-8"
        )
        written.append(PROGRESS_NAME)
    for item in payload.get("files") or []:
        if not isinstance(item, dict):
            continue
        name = Path(str(item.get("name") or "")).name
        if name not in ALLOWED_EXPORT_FILES:
            continue
        (dest / name).write_text(str(item.get("text") or ""), encoding="utf-8")
        written.append(name)
    return written
