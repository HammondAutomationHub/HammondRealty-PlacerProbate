"""Authenticated mapping UI for the HACS integration."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FUB_API_KEY,
    CONF_FUB_API_URL,
    DOMAIN,
)
from .fub_client import mapping_payload, save_mapping

WWW = Path(__file__).resolve().parent / "www"
MAP_HTML = WWW / "fub_map.html"
PANEL_URL_PATH = "placer-probate-fub"


def mapping_file(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DOMAIN)) / "fub_mapping.yaml"


def _apply_key(hass: HomeAssistant) -> None:
    import os

    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    if not entry:
        return
    settings = {**entry.data, **entry.options}

    os.environ["FUB_API_URL"] = str(
        settings.get(CONF_FUB_API_URL) or "https://api.followupboss.com/v1"
    )
    os.environ["FUB_API_KEY"] = str(settings.get(CONF_FUB_API_KEY) or "")
    os.environ["FUB_MAPPING_PATH"] = str(mapping_file(hass))


class FubMapPageView(HomeAssistantView):
    url = "/api/placer_probate_monitor/fub_map"
    name = "api:placer_probate_monitor:fub_map"
    requires_auth = True

    async def get(self, request):
        return web.FileResponse(MAP_HTML)


class FubMappingView(HomeAssistantView):
    url = "/api/placer_probate_monitor/fub_mapping"
    name = "api:placer_probate_monitor:fub_mapping"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request):
        _apply_key(self.hass)
        refresh = str(request.query.get("refresh") or "") in {"1", "true", "yes"}
        path = mapping_file(self.hass)
        payload = await self.hass.async_add_executor_job(
            lambda: mapping_payload(path, fetch_fub=refresh)
        )
        return self.json(payload)

    async def post(self, request):
        _apply_key(self.hass)
        body = await request.json()
        if not isinstance(body, dict):
            return self.json({"error": "Expected a JSON object."}, status_code=400)
        path = mapping_file(self.hass)

        def _save():
            save_mapping(body, path)
            return mapping_payload(path, fetch_fub=False)

        try:
            payload = await self.hass.async_add_executor_job(_save)
        except ValueError as exc:
            return self.json({"error": str(exc)}, status_code=400)
        return self.json(payload)


def async_setup_mapping_views(hass: HomeAssistant) -> None:
    if hass.data.setdefault(DOMAIN, {}).get("_fub_views"):
        return
    hass.http.register_view(FubMapPageView())
    hass.http.register_view(FubMappingView(hass))
    hass.data[DOMAIN]["_fub_views"] = True


def async_setup_mapping_ui(hass: HomeAssistant) -> None:
    async_setup_mapping_views(hass)
    try:
        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title="Probate FUB map",
            sidebar_icon="mdi:sitemap",
            frontend_url_path=PANEL_URL_PATH,
            config={"url": "/api/placer_probate_monitor/fub_map"},
            require_admin=True,
            update=True,
        )
    except TypeError:
        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title="Probate FUB map",
            sidebar_icon="mdi:sitemap",
            frontend_url_path=PANEL_URL_PATH,
            config={"url": "/api/placer_probate_monitor/fub_map"},
            require_admin=True,
        )


def async_unload_mapping_ui(hass: HomeAssistant) -> None:
    try:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
    except Exception:  # noqa: BLE001
        pass
