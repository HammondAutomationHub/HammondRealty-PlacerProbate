"""Config flow for Placer Probate Monitor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_COUNTY,
    CONF_ECOURT_PAUSE,
    CONF_FREQUENCY,
    CONF_FUB_API_KEY,
    CONF_FUB_API_URL,
    CONF_FUB_ASSIGNED_TO,
    CONF_FUB_STAGE,
    CONF_FUB_ENABLED,
    CONF_FUB_EVENT_TYPE,
    CONF_FUB_SOURCE,
    CONF_FUB_STRICT_PROPERTY,
    CONF_FUB_VERIFY_ONLY,
    CONF_FUB_UPDATE_EXISTING,
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
    FREQUENCIES,
    FUB_EVENT_TYPES,
    WEEKDAYS,
)


def _delivery_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_RECIPIENTS, default=defaults.get(CONF_RECIPIENTS, "")
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_FREQUENCY, default=defaults.get(CONF_FREQUENCY, "daily")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=FREQUENCIES,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="frequency",
                )
            ),
            vol.Required(
                CONF_RUN_TIME, default=defaults.get(CONF_RUN_TIME, "08:30:00")
            ): selector.TimeSelector(),
            vol.Required(
                CONF_WEEKLY_DAY, default=defaults.get(CONF_WEEKLY_DAY, "monday")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=WEEKDAYS, mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required(
                CONF_MONTHLY_DAY, default=int(defaults.get(CONF_MONTHLY_DAY, 1))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=28, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_TIMEZONE,
                default=defaults.get(CONF_TIMEZONE, "America/Los_Angeles"),
            ): selector.TextSelector(),
            vol.Required(
                CONF_SEND_EMAIL, default=bool(defaults.get(CONF_SEND_EMAIL, True))
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SMTP_HOST, default=defaults.get(CONF_SMTP_HOST, "smtp.gmail.com")
            ): selector.TextSelector(),
            vol.Required(
                CONF_SMTP_PORT, default=int(defaults.get(CONF_SMTP_PORT, 587))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_SMTP_USER, default=defaults.get(CONF_SMTP_USER, "")
            ): selector.TextSelector(),
            vol.Optional(CONF_SMTP_PASSWORD, default=""): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_MAIL_FROM, default=defaults.get(CONF_MAIL_FROM, "")
            ): selector.TextSelector(),
            vol.Required(
                CONF_RUN_ON_START, default=bool(defaults.get(CONF_RUN_ON_START, False))
            ): selector.BooleanSelector(),
        }
    )


def _search_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LOOKBACK_DAYS, default=int(defaults.get(CONF_LOOKBACK_DAYS, 21))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=120, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_LOOKAHEAD_DAYS, default=int(defaults.get(CONF_LOOKAHEAD_DAYS, 21))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=120, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_COUNTY, default=defaults.get(CONF_COUNTY, "Placer")
            ): selector.TextSelector(),
            vol.Required(
                CONF_KEYWORDS,
                default=defaults.get(CONF_KEYWORDS, DEFAULTS[CONF_KEYWORDS]),
            ): selector.TextSelector(),
            vol.Required(
                CONF_SKIP_PORTAL, default=bool(defaults.get(CONF_SKIP_PORTAL, False))
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_GENERATE_PDF, default=bool(defaults.get(CONF_GENERATE_PDF, True))
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_ECOURT_PAUSE, default=float(defaults.get(CONF_ECOURT_PAUSE, 1.2))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=10, step=0.1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_MAX_PAGES, default=int(defaults.get(CONF_MAX_PAGES, 10))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


def _fub_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_FUB_ENABLED, default=bool(defaults.get(CONF_FUB_ENABLED, False))
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_FUB_API_URL,
                default=defaults.get(
                    CONF_FUB_API_URL, "https://api.followupboss.com/v1"
                ),
            ): selector.TextSelector(),
            vol.Optional(CONF_FUB_API_KEY, default=""): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_FUB_SOURCE, default=defaults.get(CONF_FUB_SOURCE, "probate")
            ): selector.TextSelector(),
            vol.Required(
                CONF_FUB_ASSIGNED_TO,
                default=defaults.get(CONF_FUB_ASSIGNED_TO, "Blake Hammond"),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_FUB_STAGE,
                default=str(defaults.get(CONF_FUB_STAGE) or ""),
            ): selector.TextSelector(),
            vol.Required(
                CONF_FUB_EVENT_TYPE,
                default=defaults.get(CONF_FUB_EVENT_TYPE, "Seller Inquiry"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=FUB_EVENT_TYPES,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_FUB_STRICT_PROPERTY,
                default=bool(defaults.get(CONF_FUB_STRICT_PROPERTY, False)),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_FUB_VERIFY_ONLY,
                default=bool(defaults.get(CONF_FUB_VERIFY_ONLY, True)),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_FUB_UPDATE_EXISTING,
                default=bool(defaults.get(CONF_FUB_UPDATE_EXISTING, False)),
            ): selector.BooleanSelector(),
        }
    )


def _normalize(user_input: dict[str, Any], previous: dict | None = None) -> dict[str, Any]:
    data = dict(previous or {})
    data.update(user_input)
    if not data.get(CONF_SMTP_PASSWORD) and previous:
        data[CONF_SMTP_PASSWORD] = previous.get(CONF_SMTP_PASSWORD, "")
    if not data.get(CONF_FUB_API_KEY) and previous:
        data[CONF_FUB_API_KEY] = previous.get(CONF_FUB_API_KEY, "")
    for key in (
        CONF_SMTP_PORT,
        CONF_LOOKBACK_DAYS,
        CONF_LOOKAHEAD_DAYS,
        CONF_MONTHLY_DAY,
        CONF_MAX_PAGES,
    ):
        if key in data:
            data[key] = int(data[key])
    if CONF_ECOURT_PAUSE in data:
        data[CONF_ECOURT_PAUSE] = float(data[CONF_ECOURT_PAUSE])
    return data


class PlacerProbateMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = dict(DEFAULTS)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self._data = _normalize(user_input, self._data)
            return await self.async_step_search()
        return self.async_show_form(step_id="user", data_schema=_delivery_schema(self._data))

    async def async_step_search(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data = _normalize(user_input, self._data)
            return await self.async_step_fub()
        return self.async_show_form(step_id="search", data_schema=_search_schema(self._data))

    async def async_step_fub(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data = _normalize(user_input, self._data)
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Placer Probate Monitor", data=self._data)
        return self.async_show_form(step_id="fub", data_schema=_fub_schema(self._data))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return PlacerProbateMonitorOptionsFlow()


class PlacerProbateMonitorOptionsFlow(config_entries.OptionsFlow):
    def __init__(self) -> None:
        self._data: dict[str, Any] | None = None

    def _defaults(self) -> dict[str, Any]:
        if self._data is None:
            self._data = {
                **DEFAULTS,
                **self.config_entry.data,
                **self.config_entry.options,
            }
        return self._data

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        defaults = self._defaults()
        if user_input is not None:
            self._data = _normalize(user_input, defaults)
            return await self.async_step_search()
        return self.async_show_form(step_id="init", data_schema=_delivery_schema(defaults))

    async def async_step_search(self, user_input: dict[str, Any] | None = None):
        defaults = self._defaults()
        if user_input is not None:
            self._data = _normalize(user_input, defaults)
            return await self.async_step_fub()
        return self.async_show_form(step_id="search", data_schema=_search_schema(defaults))

    async def async_step_fub(self, user_input: dict[str, Any] | None = None):
        defaults = self._defaults()
        if user_input is not None:
            self._data = _normalize(user_input, defaults)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(step_id="fub", data_schema=_fub_schema(defaults))
