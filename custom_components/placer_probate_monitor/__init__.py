"""Placer Probate Monitor Home Assistant integration."""

from __future__ import annotations

import logging
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_FUB_ERROR,
    ATTR_FUB_POSTED,
    ATTR_FUB_SKIPPED,
    ATTR_FUB_UPDATED,
    ATTR_FUB_VERIFY,
    ATTR_LAST_ERROR,
    ATTR_LAST_RESULT,
    ATTR_LAST_RUN,
    ATTR_NEW_COUNT,
    ATTR_PDF,
    CONF_COUNTY,
    CONF_ECOURT_PAUSE,
    CONF_FREQUENCY,
    CONF_FUB_API_KEY,
    CONF_FUB_API_URL,
    CONF_FUB_ASSIGNED_TO,
    CONF_FUB_ENABLED,
    CONF_FUB_EVENT_TYPE,
    CONF_FUB_SOURCE,
    CONF_FUB_STRICT_PROPERTY,
    CONF_FUB_VERIFY_ONLY,
    CONF_GENERATE_PDF,
    CONF_KEYWORDS,
    CONF_LOOKAHEAD_DAYS,
    CONF_LOOKBACK_DAYS,
    CONF_MAIL_FROM,
    CONF_MAX_PAGES,
    CONF_MONTHLY_DAY,
    CONF_RECIPIENTS,
    CONF_RUN_ON_START,
    CONF_RUN_TIME,
    CONF_SEND_EMAIL,
    CONF_SKIP_PORTAL,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_PORT,
    CONF_SMTP_USER,
    CONF_TIMEZONE,
    CONF_WEEKLY_DAY,
    DEFAULTS,
    DOMAIN,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
COMPONENT_DIR = Path(__file__).resolve().parent


def merged_options(entry: ConfigEntry) -> dict:
    return {**DEFAULTS, **entry.data, **entry.options}


def parse_recipients(value) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "")
    return [
        part.strip()
        for part in text.replace(";", ",").replace("\n", ",").split(",")
        if part.strip()
    ]


def parse_run_time(value: str) -> tuple[int, int, int]:
    parts = str(value or "08:30:00").strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    second = int(float(parts[2])) if len(parts) > 2 else 0
    return hour, minute, second


def tzinfo(settings: dict) -> ZoneInfo:
    try:
        return ZoneInfo(str(settings.get(CONF_TIMEZONE) or "America/Los_Angeles"))
    except Exception:
        return ZoneInfo("America/Los_Angeles")


def apply_env(
    settings: dict,
    mapping_path: Path | None = None,
    hass: HomeAssistant | None = None,
) -> None:
    recipients = parse_recipients(settings.get(CONF_RECIPIENTS))
    os.environ["SMTP_HOST"] = str(settings.get(CONF_SMTP_HOST) or "smtp.gmail.com")
    os.environ["SMTP_PORT"] = str(int(settings.get(CONF_SMTP_PORT) or 587))
    os.environ["SMTP_USER"] = str(settings.get(CONF_SMTP_USER) or "")
    os.environ["SMTP_PASSWORD"] = str(settings.get(CONF_SMTP_PASSWORD) or "")
    os.environ["MAIL_FROM"] = str(
        settings.get(CONF_MAIL_FROM) or settings.get(CONF_SMTP_USER) or ""
    )
    os.environ["MAIL_TO"] = ",".join(recipients)
    os.environ["PROBATE_TZ"] = str(settings.get(CONF_TIMEZONE) or "America/Los_Angeles")
    os.environ["PROBATE_COUNTY"] = str(settings.get(CONF_COUNTY) or "Placer")
    os.environ["PROBATE_KEYWORDS"] = str(settings.get(CONF_KEYWORDS) or DEFAULTS[CONF_KEYWORDS])
    os.environ["PROBATE_MAX_PAGES"] = str(int(settings.get(CONF_MAX_PAGES) or 10))
    os.environ["ECOURT_PAUSE"] = str(float(settings.get(CONF_ECOURT_PAUSE) or 1.2))
    os.environ["FUB_ENABLED"] = "1" if settings.get(CONF_FUB_ENABLED) else "0"
    os.environ["FUB_API_URL"] = str(
        settings.get(CONF_FUB_API_URL) or "https://api.followupboss.com/v1"
    )
    os.environ["FUB_API_KEY"] = str(settings.get(CONF_FUB_API_KEY) or "")
    os.environ["FUB_SOURCE"] = str(settings.get(CONF_FUB_SOURCE) or "probate")
    os.environ["FUB_ASSIGNED_TO"] = str(
        settings.get(CONF_FUB_ASSIGNED_TO) or "Blake Hammond"
    )
    os.environ["FUB_EVENT_TYPE"] = str(
        settings.get(CONF_FUB_EVENT_TYPE) or "Seller Inquiry"
    )
    os.environ["FUB_STRICT_PROPERTY"] = (
        "1" if settings.get(CONF_FUB_STRICT_PROPERTY) else "0"
    )
    os.environ["FUB_VERIFY_ONLY"] = (
        "1" if settings.get(CONF_FUB_VERIFY_ONLY) else "0"
    )
    if mapping_path:
        os.environ["FUB_MAPPING_PATH"] = str(mapping_path)
    if hass is not None:
        data_dir = Path(hass.config.path(DOMAIN))
        os.environ["FUB_PETITION_DOCS_DIR"] = str(data_dir / "reports" / "docs")
        entry = hass.config_entries.async_entries(DOMAIN)
        if entry:
            os.environ["FUB_PETITION_TOKEN_SECRET"] = entry[0].entry_id
        try:
            from homeassistant.helpers.network import get_url

            base = str(get_url(hass, prefer_external=True) or "").rstrip("/")
        except Exception:  # noqa: BLE001
            base = ""
        if base:
            os.environ["FUB_PETITION_BASE_URL"] = (
                f"{base}/api/placer_probate_monitor/de111"
            )
        else:
            os.environ.pop("FUB_PETITION_BASE_URL", None)


def should_run_now(settings: dict, now: datetime) -> bool:
    freq = str(settings.get(CONF_FREQUENCY) or "daily")
    name = WEEKDAYS[now.weekday()]
    if freq == "hourly":
        return True
    if freq == "weekdays" and name in {"saturday", "sunday"}:
        return False
    if freq == "weekly" and name != str(settings.get(CONF_WEEKLY_DAY) or "monday").lower():
        return False
    if freq == "monthly" and now.day != int(settings.get(CONF_MONTHLY_DAY) or 1):
        return False
    return True


def run_monitor_job(hass: HomeAssistant, settings: dict) -> dict:
    data_dir = Path(hass.config.path(DOMAIN))
    apply_env(settings, mapping_path=data_dir / "fub_mapping.yaml", hass=hass)
    reports = data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(COMPONENT_DIR / "placer_probate_monitor.py"),
        "--lookback-days",
        str(int(settings.get(CONF_LOOKBACK_DAYS) or 21)),
        "--lookahead-days",
        str(int(settings.get(CONF_LOOKAHEAD_DAYS) or 21)),
        "--state-file",
        str(data_dir / "seen_cases.json"),
        "--out-dir",
        str(reports),
    ]
    if not settings.get(CONF_SEND_EMAIL):
        cmd.append("--no-email")
    if settings.get(CONF_SKIP_PORTAL):
        cmd.append("--skip-portal")
    if not settings.get(CONF_GENERATE_PDF):
        cmd.append("--no-pdf")
    if settings.get("fub_preview_one"):
        cmd.append("--fub-preview-one")
        if "--no-email" not in cmd:
            cmd.append("--no-email")
        if "--no-pdf" not in cmd:
            cmd.append("--no-pdf")
    elif settings.get(CONF_FUB_VERIFY_ONLY):
        cmd.append("--fub-verify-one")
    proc = subprocess.run(
        cmd,
        cwd=str(COMPONENT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    (data_dir / "last_run.log").write_text(log, encoding="utf-8")
    pdfs = sorted(reports.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
    new_count = None
    for line in reversed(log.splitlines()):
        if " new / " in line and "Placer probate notices" in line:
            try:
                new_count = int(line.split("—")[-1].split("new")[0].strip())
            except ValueError:
                pass
            break
    ok = proc.returncode == 0
    fub_posted = None
    fub_updated = None
    fub_skipped = None
    fub_error = None
    fub_verify = None
    sidecar = data_dir / "fub_last.json"
    if sidecar.exists():
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            fub_posted = payload.get("posted")
            fub_updated = payload.get("updated")
            fub_skipped = payload.get("skipped")
            fub_error = payload.get("error")
            fub_verify = payload.get("verify_record")
            if not fub_verify and payload.get("verify_note"):
                fub_verify = {"note": payload.get("verify_note")}
        except json.JSONDecodeError:
            pass
    if fub_posted is None:
        for line in reversed(log.splitlines()):
            if line.startswith("FUB: posted="):
                try:
                    parts = dict(
                        item.split("=", 1) for item in line.replace("FUB: ", "").split()
                    )
                    fub_posted = int(parts.get("posted", 0))
                    fub_updated = int(parts.get("updated", 0))
                    fub_skipped = int(parts.get("skipped", 0))
                except ValueError:
                    pass
                break
    if fub_error is None:
        for line in reversed(log.splitlines()):
            if line.startswith("FUB enabled but") or line.startswith("FUB error"):
                fub_error = line[-500:]
                break
    return {
        "ok": ok,
        ATTR_LAST_RESULT: "ok" if ok else "failed",
        ATTR_LAST_ERROR: None if ok else (log[-2000:] or f"exit {proc.returncode}"),
        ATTR_PDF: pdfs[0].name if pdfs else None,
        ATTR_NEW_COUNT: new_count,
        ATTR_FUB_POSTED: fub_posted,
        ATTR_FUB_UPDATED: fub_updated,
        ATTR_FUB_SKIPPED: fub_skipped,
        ATTR_FUB_ERROR: fub_error,
        ATTR_FUB_VERIFY: fub_verify,
        "log_tail": log[-1500:],
    }


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    from .hass_views import async_setup_mapping_views

    async_setup_mapping_views(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    store = {
        "entry": entry,
        "unsubs": [],
        "running": False,
        "status": {
            ATTR_LAST_RUN: None,
            ATTR_LAST_RESULT: None,
            ATTR_LAST_ERROR: None,
            ATTR_NEW_COUNT: None,
            ATTR_PDF: None,
            ATTR_FUB_POSTED: None,
            ATTR_FUB_UPDATED: None,
            ATTR_FUB_SKIPPED: None,
            ATTR_FUB_ERROR: None,
            ATTR_FUB_VERIFY: None,
        },
    }
    hass.data[DOMAIN][entry.entry_id] = store

    async def _execute(reason: str, overrides: dict | None = None) -> dict:
        if store["running"]:
            return {"ok": False, "error": "A run is already in progress."}
        store["running"] = True
        async_dispatcher_send(hass, f"{DOMAIN}_status")
        settings = {**merged_options(entry), **(overrides or {})}
        try:
            result = await hass.async_add_executor_job(run_monitor_job, hass, settings)
        except Exception:
            _LOGGER.exception("Placer probate monitor failed")
            result = {
                "ok": False,
                ATTR_LAST_RESULT: "failed",
                ATTR_LAST_ERROR: "Monitor raised an exception; see Home Assistant logs.",
            }
        zone = tzinfo(settings)
        store["status"].update(
            {
                ATTR_LAST_RUN: datetime.now(zone).isoformat(timespec="seconds"),
                ATTR_LAST_RESULT: result.get(ATTR_LAST_RESULT),
                ATTR_LAST_ERROR: result.get(ATTR_LAST_ERROR),
                ATTR_NEW_COUNT: result.get(ATTR_NEW_COUNT),
                ATTR_PDF: result.get(ATTR_PDF),
                ATTR_FUB_POSTED: result.get(ATTR_FUB_POSTED),
                ATTR_FUB_UPDATED: result.get(ATTR_FUB_UPDATED),
                ATTR_FUB_SKIPPED: result.get(ATTR_FUB_SKIPPED),
                ATTR_FUB_ERROR: result.get(ATTR_FUB_ERROR),
                ATTR_FUB_VERIFY: result.get(ATTR_FUB_VERIFY),
            }
        )
        store["running"] = False
        async_dispatcher_send(hass, f"{DOMAIN}_status")
        _LOGGER.info("Placer probate monitor %s run: %s", reason, result.get(ATTR_LAST_RESULT))
        return result

    async def _scheduled(_now=None) -> None:
        settings = merged_options(entry)
        current = datetime.now(tzinfo(settings))
        if should_run_now(settings, current):
            await _execute("scheduled")

    def _listen() -> None:
        for unsub in store["unsubs"]:
            unsub()
        store["unsubs"] = []
        settings = merged_options(entry)
        hour, minute, second = parse_run_time(str(settings.get(CONF_RUN_TIME) or "08:30:00"))
        freq = str(settings.get(CONF_FREQUENCY) or "daily")
        if freq == "hourly":
            store["unsubs"].append(
                async_track_time_change(hass, _scheduled, minute=minute, second=second)
            )
        else:
            store["unsubs"].append(
                async_track_time_change(
                    hass, _scheduled, hour=hour, minute=minute, second=second
                )
            )

    _listen()
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    async def _start(_event=None) -> None:
        if merged_options(entry).get(CONF_RUN_ON_START):
            await _execute("startup")

    if hass.is_running:
        hass.async_create_task(_start())
    else:
        store["unsubs"].append(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start))

    store["run"] = _execute
    store["relisten"] = _listen

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    from .hass_views import async_setup_mapping_ui

    async_setup_mapping_ui(hass)

    async def _svc_run(_call: ServiceCall) -> None:
        result = await _execute("service")
        hass.bus.async_fire(f"{DOMAIN}_run_finished", result)

    async def _svc_test(_call: ServiceCall) -> None:
        settings = merged_options(entry)
        apply_env(settings)
        if not parse_recipients(settings.get(CONF_RECIPIENTS)):
            raise HomeAssistantError("Add at least one recipient.")

        def _send() -> None:
            from .placer_probate_monitor import send_email

            send_email(
                "Placer probate monitor — test",
                "This is a test from the Home Assistant integration. SMTP is working.",
                "<p>This is a test from the Home Assistant integration. SMTP is working.</p>",
            )

        await hass.async_add_executor_job(_send)

    async def _svc_verify(_call: ServiceCall) -> None:
        settings = merged_options(entry)
        if not str(settings.get(CONF_FUB_API_KEY) or "").strip():
            raise HomeAssistantError("Set the Follow Up Boss API key first.")
        result = await _execute(
            "verify_fub",
            {
                CONF_FUB_ENABLED: True,
                CONF_FUB_VERIFY_ONLY: True,
                CONF_SEND_EMAIL: False,
            },
        )
        hass.bus.async_fire(f"{DOMAIN}_run_finished", result)

    async def _svc_preview(_call: ServiceCall) -> None:
        result = await _execute(
            "preview_one",
            {
                "fub_preview_one": True,
                CONF_FUB_VERIFY_ONLY: False,
                CONF_SEND_EMAIL: False,
                CONF_GENERATE_PDF: False,
            },
        )
        hass.bus.async_fire(f"{DOMAIN}_run_finished", result)

    hass.services.async_register(DOMAIN, "run_now", _svc_run)
    hass.services.async_register(DOMAIN, "test_email", _svc_test)
    hass.services.async_register(DOMAIN, "verify_fub", _svc_verify)
    hass.services.async_register(DOMAIN, "preview_one", _svc_preview)
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    store["relisten"]()
    async_dispatcher_send(hass, f"{DOMAIN}_status")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = hass.data[DOMAIN].pop(entry.entry_id, None)
    if store:
        for unsub in store.get("unsubs") or []:
            unsub()
    remaining = [
        key for key in (hass.data.get(DOMAIN) or {}) if key != "_fub_views"
    ]
    if not remaining:
        hass.services.async_remove(DOMAIN, "run_now")
        hass.services.async_remove(DOMAIN, "test_email")
        hass.services.async_remove(DOMAIN, "verify_fub")
        hass.services.async_remove(DOMAIN, "preview_one")
        from .hass_views import async_unload_mapping_ui

        async_unload_mapping_ui(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
