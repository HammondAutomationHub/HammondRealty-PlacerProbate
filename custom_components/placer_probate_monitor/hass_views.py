"""Authenticated source and Follow Up Boss screens for the HACS integration."""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    ATTR_FUB_VERIFY,
    CONF_ECOURT_PAUSE,
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
    CONF_MAX_PAGES,
    CONF_SEND_EMAIL,
    CONF_SKIP_PORTAL,
    DEFAULTS,
    DOMAIN,
    FUB_EVENT_TYPES,
)
from .fub_client import inspect_fub_person, mapping_payload, save_mapping, sources_payload

PANEL_JS_VERSION = "1.3.11"

WWW = Path(__file__).resolve().parent / "www"
MAP_HTML = WWW / "fub_map.html"
PANEL_JS = WWW / "panel.js"
PANEL_FUB_PATH = "placer-probate-fub"
PANEL_SOURCES_PATH = "placer-probate-sources"

SOURCE_KEYS = {
    CONF_LOOKBACK_DAYS,
    CONF_LOOKAHEAD_DAYS,
    CONF_KEYWORDS,
    CONF_SKIP_PORTAL,
    CONF_GENERATE_PDF,
    CONF_ECOURT_PAUSE,
    CONF_MAX_PAGES,
}
FUB_KEYS = {
    CONF_FUB_ENABLED,
    CONF_FUB_API_URL,
    CONF_FUB_API_KEY,
    CONF_FUB_SOURCE,
    CONF_FUB_ASSIGNED_TO,
    CONF_FUB_EVENT_TYPE,
    CONF_FUB_STRICT_PROPERTY,
    CONF_FUB_VERIFY_ONLY,
}
INT_KEYS = {CONF_LOOKBACK_DAYS, CONF_LOOKAHEAD_DAYS, CONF_MAX_PAGES}
BOOL_KEYS = {
    CONF_SKIP_PORTAL,
    CONF_GENERATE_PDF,
    CONF_FUB_ENABLED,
    CONF_FUB_STRICT_PROPERTY,
    CONF_FUB_VERIFY_ONLY,
}


def _fub_last(hass: HomeAssistant) -> dict:
    path = Path(hass.config.path(DOMAIN)) / "fub_last.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def mapping_file(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DOMAIN)) / "fub_mapping.yaml"


def _entry(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _store(hass: HomeAssistant):
    entry = _entry(hass)
    if not entry:
        return None
    return (hass.data.get(DOMAIN) or {}).get(entry.entry_id)


def _merged(entry) -> dict:
    return {**DEFAULTS, **entry.data, **entry.options}


def _apply_key(hass: HomeAssistant) -> None:
    import os

    entry = _entry(hass)
    if not entry:
        return
    settings = _merged(entry)
    os.environ["FUB_API_URL"] = str(
        settings.get(CONF_FUB_API_URL) or "https://api.followupboss.com/v1"
    )
    os.environ["FUB_API_KEY"] = str(settings.get(CONF_FUB_API_KEY) or "")
    os.environ["FUB_MAPPING_PATH"] = str(mapping_file(hass))


def _coerce(key: str, value):
    if key in BOOL_KEYS:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if key in INT_KEYS:
        return int(value)
    if key == CONF_ECOURT_PAUSE:
        return float(value)
    return value


def _public_fub(settings: dict) -> dict:
    key = str(settings.get(CONF_FUB_API_KEY) or "")
    return {
        CONF_FUB_ENABLED: bool(settings.get(CONF_FUB_ENABLED)),
        CONF_FUB_API_URL: settings.get(CONF_FUB_API_URL)
        or "https://api.followupboss.com/v1",
        CONF_FUB_API_KEY: "",
        "fub_api_key_set": bool(key),
        CONF_FUB_SOURCE: settings.get(CONF_FUB_SOURCE) or "probate",
        CONF_FUB_ASSIGNED_TO: settings.get(CONF_FUB_ASSIGNED_TO) or "Blake Hammond",
        CONF_FUB_EVENT_TYPE: settings.get(CONF_FUB_EVENT_TYPE) or "Seller Inquiry",
        CONF_FUB_STRICT_PROPERTY: bool(settings.get(CONF_FUB_STRICT_PROPERTY)),
        CONF_FUB_VERIFY_ONLY: bool(settings.get(CONF_FUB_VERIFY_ONLY, True)),
        "event_types": FUB_EVENT_TYPES,
    }


class FubMapPageView(HomeAssistantView):
    url = "/api/placer_probate_monitor/fub_map"
    name = "api:placer_probate_monitor:fub_map"
    requires_auth = True

    async def get(self, request):
        return web.FileResponse(MAP_HTML)


class FubPanelJsView(HomeAssistantView):
    """Frontend loads this without a bearer token."""

    url = "/api/placer_probate_monitor/panel.js"
    name = "api:placer_probate_monitor:panel_js"
    requires_auth = False

    async def get(self, request):
        return web.FileResponse(
            PANEL_JS,
            headers={
                "Cache-Control": "no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )


class FubMappingView(HomeAssistantView):
    url = "/api/placer_probate_monitor/fub_mapping"
    name = "api:placer_probate_monitor:fub_mapping"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request):
        _apply_key(self.hass)
        path = mapping_file(self.hass)
        source_id = str(request.query.get("source") or "placer")
        payload = await self.hass.async_add_executor_job(
            lambda: mapping_payload(path, fetch_fub=True, source_id=source_id)
        )
        return self.json(payload)

    async def post(self, request):
        _apply_key(self.hass)
        body = await request.json()
        if not isinstance(body, dict):
            return self.json({"error": "Expected a JSON object."}, status_code=400)
        path = mapping_file(self.hass)
        source_id = str(body.get("source_id") or "placer")

        def _save():
            save_mapping(body, path)
            return mapping_payload(path, fetch_fub=True, source_id=source_id)

        try:
            payload = await self.hass.async_add_executor_job(_save)
        except ValueError as exc:
            return self.json({"error": str(exc)}, status_code=400)
        return self.json(payload)


class FubPersonView(HomeAssistantView):
    url = "/api/placer_probate_monitor/fub_person"
    name = "api:placer_probate_monitor:fub_person"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request):
        _apply_key(self.hass)
        query = str(request.query.get("q") or request.query.get("id") or "")
        payload = await self.hass.async_add_executor_job(inspect_fub_person, query)
        status = 200 if payload.get("person_id") else 400
        return self.json(payload, status_code=status)


class SourcesView(HomeAssistantView):
    url = "/api/placer_probate_monitor/sources"
    name = "api:placer_probate_monitor:sources"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request):
        entry = _entry(self.hass)
        settings = _merged(entry) if entry else dict(DEFAULTS)
        return self.json(sources_payload(settings))

    async def post(self, request):
        entry = _entry(self.hass)
        if not entry:
            return self.json({"error": "Integration is not configured."}, status_code=400)
        body = await request.json()
        if not isinstance(body, dict):
            return self.json({"error": "Expected a JSON object."}, status_code=400)
        merged = _merged(entry)
        for key in SOURCE_KEYS:
            if key not in body:
                continue
            try:
                merged[key] = _coerce(key, body[key])
            except (TypeError, ValueError):
                return self.json({"error": f"Invalid {key}."}, status_code=400)
        merged["county"] = "Placer"
        self.hass.config_entries.async_update_entry(entry, options=merged)
        return self.json(sources_payload(merged))


class FubSettingsView(HomeAssistantView):
    url = "/api/placer_probate_monitor/fub_settings"
    name = "api:placer_probate_monitor:fub_settings"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request):
        entry = _entry(self.hass)
        settings = _merged(entry) if entry else dict(DEFAULTS)
        return self.json(_public_fub(settings))

    async def post(self, request):
        entry = _entry(self.hass)
        if not entry:
            return self.json({"error": "Integration is not configured."}, status_code=400)
        body = await request.json()
        if not isinstance(body, dict):
            return self.json({"error": "Expected a JSON object."}, status_code=400)
        merged = _merged(entry)
        for key in FUB_KEYS:
            if key not in body:
                continue
            if key == CONF_FUB_API_KEY:
                value = str(body[key] or "").strip()
                if not value or value in {"••••••••", "********"}:
                    continue
                merged[key] = value
                continue
            try:
                merged[key] = _coerce(key, body[key])
            except (TypeError, ValueError):
                return self.json({"error": f"Invalid {key}."}, status_code=400)
        self.hass.config_entries.async_update_entry(entry, options=merged)
        return self.json(_public_fub(merged))


class JobView(HomeAssistantView):
    url = "/api/placer_probate_monitor/job"
    name = "api:placer_probate_monitor:job"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _status(self) -> dict | None:
        store = _store(self.hass)
        if not store:
            return None
        payload = dict(store.get("status") or {})
        payload["running"] = bool(store.get("running"))
        last = _fub_last(self.hass)
        if last.get("verify_record"):
            payload[ATTR_FUB_VERIFY] = last.get("verify_record")
        elif last.get("verify_note"):
            payload[ATTR_FUB_VERIFY] = {"note": last.get("verify_note")}
        if last.get("verify_note"):
            payload["fub_verify_note"] = last.get("verify_note")
        payload["fub_skips"] = last.get("skips") or []
        payload["fub_preview"] = bool(last.get("preview"))
        if last.get("error"):
            payload["fub_error"] = last.get("error")
        return payload

    async def get(self, request):
        status = self._status()
        if status is None:
            return self.json({"error": "Integration is not configured."}, status_code=400)
        return self.json(status)

    async def post(self, request):
        store = _store(self.hass)
        entry = _entry(self.hass)
        runner = (store or {}).get("run") if store else None
        if not store or not runner or not entry:
            return self.json({"error": "Integration is not configured."}, status_code=400)
        if store.get("running"):
            return self.json(
                {"ok": False, "error": "A run is already in progress.", "running": True},
                status_code=409,
            )
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            body = {}
        action = str(body.get("action") or "run")
        if action == "verify":
            settings = _merged(entry)
            if not str(settings.get(CONF_FUB_API_KEY) or "").strip():
                return self.json(
                    {"ok": False, "error": "Set the Follow Up Boss API key first."},
                    status_code=400,
                )
            self.hass.async_create_task(
                runner(
                    "verify_fub",
                    {
                        CONF_FUB_ENABLED: True,
                        CONF_FUB_VERIFY_ONLY: True,
                        CONF_SEND_EMAIL: False,
                    },
                )
            )
        elif action == "preview":
            self.hass.async_create_task(
                runner(
                    "preview_one",
                    {
                        "fub_preview_one": True,
                        CONF_FUB_VERIFY_ONLY: False,
                        CONF_SEND_EMAIL: False,
                        CONF_GENERATE_PDF: False,
                    },
                )
            )
        else:
            self.hass.async_create_task(runner("panel"))
        return self.json({"ok": True, "started": True, "action": action})


def _register_panel(hass: HomeAssistant, url_path: str, title: str, icon: str, element: str) -> None:
    config = {
        "_panel_custom": {
            "name": element,
            "embed_iframe": True,
            "trust_external": False,
            "js_url": f"/api/placer_probate_monitor/panel.js?v={PANEL_JS_VERSION}",
        }
    }
    kwargs = {
        "component_name": "custom",
        "sidebar_title": title,
        "sidebar_icon": icon,
        "frontend_url_path": url_path,
        "config": config,
        "require_admin": True,
    }
    try:
        frontend.async_register_built_in_panel(hass, **kwargs, update=True)
    except TypeError:
        try:
            frontend.async_remove_panel(hass, url_path)
        except Exception:  # noqa: BLE001
            pass
        frontend.async_register_built_in_panel(hass, **kwargs)


def async_setup_mapping_views(hass: HomeAssistant) -> None:
    if hass.data.setdefault(DOMAIN, {}).get("_fub_views"):
        return
    hass.http.register_view(FubMapPageView())
    hass.http.register_view(FubPanelJsView())
    hass.http.register_view(FubMappingView(hass))
    hass.http.register_view(FubPersonView(hass))
    hass.http.register_view(SourcesView(hass))
    hass.http.register_view(FubSettingsView(hass))
    hass.http.register_view(JobView(hass))
    hass.data[DOMAIN]["_fub_views"] = True


def async_setup_mapping_ui(hass: HomeAssistant) -> None:
    async_setup_mapping_views(hass)
    _register_panel(
        hass,
        PANEL_SOURCES_PATH,
        "Probate sources",
        "mdi:database-search",
        "placer-probate-sources-panel",
    )
    _register_panel(
        hass,
        PANEL_FUB_PATH,
        "Follow Up Boss",
        "mdi:account-arrow-up",
        "placer-probate-fub-panel",
    )


def async_unload_mapping_ui(hass: HomeAssistant) -> None:
    for path in (PANEL_FUB_PATH, PANEL_SOURCES_PATH):
        try:
            frontend.async_remove_panel(hass, path)
        except Exception:  # noqa: BLE001
            pass
