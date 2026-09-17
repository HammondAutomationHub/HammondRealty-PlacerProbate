#!/usr/bin/env python3
"""Home Assistant add-on process: scheduler + ingress web UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_file, send_from_directory

ROOT = Path(__file__).resolve().parent
IN_HA = Path("/data").is_dir() and Path("/data/options.json").exists()
DATA = Path("/data") if Path("/data").is_dir() else ROOT / "data"
SETTINGS_PATH = DATA / "ui_settings.json"
STATUS_PATH = DATA / "run_status.json"
OPTIONS_PATH = Path("/data/options.json")
WWW = ROOT / "www"

DEFAULTS = {
    "recipients": [],
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "mail_from": "",
    "send_email": True,
    "frequency": "daily",
    "run_time": "08:30",
    "weekly_day": "monday",
    "monthly_day": 1,
    "timezone": "America/Los_Angeles",
    "run_on_start": False,
    "lookback_days": 21,
    "lookahead_days": 21,
    "county": "Placer",
    "keywords": '"NOTICE OF PETITION TO ADMINISTER ESTATE"',
    "skip_portal": False,
    "generate_pdf": True,
    "ecourt_pause_seconds": 1.2,
    "max_search_pages": 10,
}

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

app = Flask(__name__, static_folder=str(WWW), static_url_path="")
_lock = threading.Lock()
_run_lock = threading.Lock()


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_settings() -> dict:
    with _lock:
        merged = dict(DEFAULTS)
        if OPTIONS_PATH.exists():
            merged.update(_read_json(OPTIONS_PATH, {}))
        if SETTINGS_PATH.exists():
            merged.update(_read_json(SETTINGS_PATH, {}))
        rec = merged.get("recipients") or []
        if isinstance(rec, str):
            rec = [x.strip() for x in rec.replace(";", ",").split(",") if x.strip()]
        merged["recipients"] = [str(x).strip() for x in rec if str(x).strip()]
        merged["smtp_port"] = int(merged.get("smtp_port") or 587)
        merged["lookback_days"] = int(merged.get("lookback_days") or 21)
        merged["lookahead_days"] = int(merged.get("lookahead_days") or 21)
        merged["monthly_day"] = int(merged.get("monthly_day") or 1)
        merged["max_search_pages"] = int(merged.get("max_search_pages") or 10)
        merged["ecourt_pause_seconds"] = float(merged.get("ecourt_pause_seconds") or 1.2)
        return merged


def save_settings(incoming: dict) -> dict:
    current = load_settings()
    for key in DEFAULTS:
        if key in incoming:
            current[key] = incoming[key]
    rec = current.get("recipients") or []
    if isinstance(rec, str):
        rec = [x.strip() for x in rec.replace(";", ",").split(",") if x.strip()]
    current["recipients"] = [str(x).strip() for x in rec if str(x).strip()]
    _write_json(SETTINGS_PATH, current)
    _push_supervisor_options(current)
    return current


def _push_supervisor_options(settings: dict) -> None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    try:
        import urllib.request

        body = json.dumps({"options": {k: settings[k] for k in DEFAULTS}}).encode()
        req = urllib.request.Request(
            "http://supervisor/addons/self/options",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:
        print(f"Supervisor options sync skipped: {exc}", file=sys.stderr)


def load_status() -> dict:
    return _read_json(
        STATUS_PATH,
        {
            "state": "idle",
            "last_run": None,
            "last_result": None,
            "last_error": None,
            "next_run": None,
            "running": False,
        },
    )


def save_status(**updates) -> dict:
    status = load_status()
    status.update(updates)
    _write_json(STATUS_PATH, status)
    return status


def tzinfo(settings: dict | None = None):
    settings = settings or load_settings()
    try:
        return ZoneInfo(str(settings.get("timezone") or "America/Los_Angeles"))
    except Exception:
        return ZoneInfo("America/Los_Angeles")


def parse_run_time(value: str) -> tuple[int, int]:
    raw = (value or "08:30").strip()
    parts = raw.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return max(0, min(23, hour)), max(0, min(59, minute))


def last_run_dt(status: dict, zone) -> datetime | None:
    raw = status.get("last_run")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
        return dt.astimezone(zone)
    except ValueError:
        return None


def next_run_at(settings: dict, status: dict) -> datetime:
    zone = tzinfo(settings)
    now = datetime.now(zone)
    hour, minute = parse_run_time(str(settings.get("run_time") or "08:30"))
    freq = str(settings.get("frequency") or "daily")
    last = last_run_dt(status, zone)
    weekly_day = str(settings.get("weekly_day") or "monday").lower()
    monthly_day = int(settings.get("monthly_day") or 1)

    if freq == "hourly":
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate < now:
            candidate += timedelta(hours=1)
        return candidate

    for offset in range(0, 400):
        day = (now + timedelta(days=offset)).date()
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        name = WEEKDAYS[candidate.weekday()]
        if freq == "weekdays" and name in {"saturday", "sunday"}:
            continue
        if freq == "weekly" and name != weekly_day:
            continue
        if freq == "monthly" and candidate.day != monthly_day:
            continue
        if candidate <= now:
            continue
        if last and last.date() == candidate.date() and last >= candidate - timedelta(minutes=5):
            continue
        return candidate
    return now + timedelta(days=1)


def apply_env(settings: dict) -> None:
    recipients = settings.get("recipients") or []
    os.environ["SMTP_HOST"] = str(settings.get("smtp_host") or "smtp.gmail.com")
    os.environ["SMTP_PORT"] = str(int(settings.get("smtp_port") or 587))
    os.environ["SMTP_USER"] = str(settings.get("smtp_user") or "")
    os.environ["SMTP_PASSWORD"] = str(settings.get("smtp_password") or "")
    os.environ["MAIL_FROM"] = str(settings.get("mail_from") or settings.get("smtp_user") or "")
    os.environ["MAIL_TO"] = ",".join(recipients)
    os.environ["PROBATE_TZ"] = str(settings.get("timezone") or "America/Los_Angeles")
    os.environ["PROBATE_COUNTY"] = str(settings.get("county") or "Placer")
    os.environ["PROBATE_KEYWORDS"] = str(
        settings.get("keywords") or '"NOTICE OF PETITION TO ADMINISTER ESTATE"'
    )
    os.environ["PROBATE_MAX_PAGES"] = str(int(settings.get("max_search_pages") or 10))
    os.environ["ECOURT_PAUSE"] = str(float(settings.get("ecourt_pause_seconds") or 1.2))


def reports_dir() -> Path:
    path = DATA / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_job(reason: str = "scheduled") -> dict:
    if not _run_lock.acquire(blocking=False):
        return {"ok": False, "error": "A run is already in progress."}
    settings = load_settings()
    apply_env(settings)
    save_status(state="running", running=True, last_error=None)
    zone = tzinfo(settings)
    started = datetime.now(zone).isoformat(timespec="seconds")
    cmd = [
        sys.executable,
        str(ROOT / "placer_probate_monitor.py"),
        "--lookback-days",
        str(int(settings.get("lookback_days") or 21)),
        "--lookahead-days",
        str(int(settings.get("lookahead_days") or 21)),
        "--state-file",
        str(DATA / "seen_cases.json"),
        "--out-dir",
        str(reports_dir()),
    ]
    if not settings.get("send_email"):
        cmd.append("--no-email")
    if settings.get("skip_portal"):
        cmd.append("--skip-portal")
    if not settings.get("generate_pdf"):
        cmd.append("--no-pdf")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "last_run.log").write_text(log, encoding="utf-8")
        ok = proc.returncode == 0
        pdfs = sorted(reports_dir().glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        result = {
            "ok": ok,
            "reason": reason,
            "exit_code": proc.returncode,
            "pdf": pdfs[0].name if pdfs else None,
        }
        save_status(
            state="idle",
            running=False,
            last_run=started,
            last_result="ok" if ok else "failed",
            last_error=None if ok else (log[-2000:] or f"exit {proc.returncode}"),
        )
        result["log_tail"] = log[-1500:]
        return result
    except Exception as exc:
        save_status(
            state="idle",
            running=False,
            last_run=started,
            last_result="failed",
            last_error=str(exc),
        )
        traceback.print_exc()
        return {"ok": False, "error": str(exc)}
    finally:
        _run_lock.release()
        settings = load_settings()
        status = load_status()
        nxt = next_run_at(settings, status)
        save_status(next_run=nxt.isoformat(timespec="seconds"), running=False, state="idle")


def scheduler_loop() -> None:
    while True:
        try:
            settings = load_settings()
            status = load_status()
            nxt = next_run_at(settings, status)
            save_status(next_run=nxt.isoformat(timespec="seconds"))
            now = datetime.now(tzinfo(settings))
            if not status.get("running") and now >= nxt:
                print(f"Scheduled run due at {nxt.isoformat()}", flush=True)
                run_job("scheduled")
        except Exception:
            traceback.print_exc()
        threading.Event().wait(20)


@app.get("/")
def index():
    return send_from_directory(WWW, "index.html")


@app.get("/api/config")
def api_config():
    settings = load_settings()
    safe = dict(settings)
    if safe.get("smtp_password"):
        safe["smtp_password"] = "••••••••"
        safe["smtp_password_set"] = True
    else:
        safe["smtp_password"] = ""
        safe["smtp_password_set"] = False
    return jsonify(safe)


@app.post("/api/config")
def api_config_save():
    body = request.get_json(force=True, silent=True) or {}
    current = load_settings()
    if body.get("smtp_password") in ("", "••••••••", None):
        body["smtp_password"] = current.get("smtp_password") or ""
    saved = save_settings(body)
    status = load_status()
    nxt = next_run_at(saved, status)
    save_status(next_run=nxt.isoformat(timespec="seconds"))
    public = dict(saved)
    public["smtp_password"] = "••••••••" if saved.get("smtp_password") else ""
    public["smtp_password_set"] = bool(saved.get("smtp_password"))
    public["next_run"] = nxt.isoformat(timespec="seconds")
    return jsonify(public)


@app.get("/api/status")
def api_status():
    settings = load_settings()
    status = load_status()
    nxt = next_run_at(settings, status)
    status["next_run"] = nxt.isoformat(timespec="seconds")
    status["timezone"] = settings.get("timezone")
    status["frequency"] = settings.get("frequency")
    status["recipients"] = settings.get("recipients") or []
    return jsonify(status)


@app.post("/api/run")
def api_run():
    result = run_job("manual")
    code = 200 if result.get("ok") else 409 if "already" in str(result.get("error") or "") else 500
    if result.get("ok"):
        code = 200
    return jsonify(result), code


@app.post("/api/test-email")
def api_test_email():
    settings = load_settings()
    apply_env(settings)
    if not settings.get("recipients"):
        return jsonify({"ok": False, "error": "Add at least one recipient."}), 400
    try:
        from placer_probate_monitor import send_email

        send_email(
            "Placer probate monitor — test",
            "This is a test from the Home Assistant add-on. SMTP is working.",
            "<p>This is a test from the Home Assistant add-on. SMTP is working.</p>",
        )
        return jsonify({"ok": True})
    except SystemExit as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/reports")
def api_reports():
    files = []
    for path in sorted(reports_dir().glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.suffix.lower() not in {".pdf", ".html", ".txt", ".json"}:
            continue
        files.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    return jsonify(files[:40])


@app.get("/api/reports/<name>")
def api_report_file(name: str):
    path = reports_dir() / Path(name).name
    if not path.exists() or not path.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(path, as_attachment=True)


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    reports_dir()
    settings = load_settings()
    if not SETTINGS_PATH.exists():
        _write_json(SETTINGS_PATH, {k: settings[k] for k in DEFAULTS})
    status = load_status()
    nxt = next_run_at(settings, status)
    save_status(next_run=nxt.isoformat(timespec="seconds"), running=False, state="idle")
    threading.Thread(target=scheduler_loop, name="probate-scheduler", daemon=True).start()
    if settings.get("run_on_start"):
        threading.Thread(target=lambda: run_job("startup"), daemon=True).start()
    print(f"Probate monitor UI on port 8099 · next run {nxt.isoformat()}", flush=True)
    app.run(host="0.0.0.0", port=int(os.environ.get("INGRESS_PORT", "8099")), debug=False)


if __name__ == "__main__":
    main()
