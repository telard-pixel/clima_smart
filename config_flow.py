"""Config and options flow for Clima Smart."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE,
    CONF_DAY_START,
    CONF_ECO_BAND,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_ECO_SWITCH,
    CONF_MORNING_OFF_START,
    CONF_MUTE_SWITCH,
    CONF_NIGHT_START,
    CONF_NIGHT_SWITCH,
    CONF_OUTDOOR,
    CONF_OUTDOOR_FALLBACK,
    CONF_OVERRIDE_MINUTES,
    CONF_PRESENCE,
    CONF_SUMMER_THRESHOLD,
    CONF_TARGET_AWAY,
    CONF_TARGET_HOME,
    DEFAULT_DAY_START,
    DEFAULT_ECO_BAND,
    DEFAULT_ECO_OUTDOOR_OFF,
    DEFAULT_ECO_OUTDOOR_ON,
    DEFAULT_MORNING_OFF_START,
    DEFAULT_NIGHT_START,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_SUMMER_THRESHOLD,
    DEFAULT_TARGET_AWAY,
    DEFAULT_TARGET_HOME,
    DOMAIN,
)


def _entity(domain: str) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain)
    )


def _setup_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CLIMATE, default=defaults.get(CONF_CLIMATE)): _entity(
                "climate"
            ),
            vol.Optional(
                CONF_PRESENCE, default=defaults.get(CONF_PRESENCE, vol.UNDEFINED)
            ): _entity("device_tracker"),
            vol.Optional(
                CONF_OUTDOOR, default=defaults.get(CONF_OUTDOOR, vol.UNDEFINED)
            ): _entity("sensor"),
            vol.Optional(
                CONF_OUTDOOR_FALLBACK,
                default=defaults.get(CONF_OUTDOOR_FALLBACK, vol.UNDEFINED),
            ): _entity("sensor"),
            vol.Optional(
                CONF_ECO_SWITCH, default=defaults.get(CONF_ECO_SWITCH, vol.UNDEFINED)
            ): _entity("switch"),
            vol.Optional(
                CONF_MUTE_SWITCH, default=defaults.get(CONF_MUTE_SWITCH, vol.UNDEFINED)
            ): _entity("switch"),
            vol.Optional(
                CONF_NIGHT_SWITCH,
                default=defaults.get(CONF_NIGHT_SWITCH, vol.UNDEFINED),
            ): _entity("switch"),
        }
    )


class ClimaSmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CLIMATE])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Clima Smart", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_setup_schema({})
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return ClimaSmartOptionsFlow()


class ClimaSmartOptionsFlow(OptionsFlow):
    """Tune behaviour without editing code."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = {**self.config_entry.data, **self.config_entry.options}

        def _num(key, default):
            return opts.get(key, default)

        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET_HOME, default=_num(CONF_TARGET_HOME, DEFAULT_TARGET_HOME)): vol.Coerce(float),
                vol.Required(CONF_TARGET_AWAY, default=_num(CONF_TARGET_AWAY, DEFAULT_TARGET_AWAY)): vol.Coerce(float),
                vol.Required(CONF_ECO_BAND, default=_num(CONF_ECO_BAND, DEFAULT_ECO_BAND)): vol.Coerce(float),
                vol.Required(CONF_ECO_OUTDOOR_ON, default=_num(CONF_ECO_OUTDOOR_ON, DEFAULT_ECO_OUTDOOR_ON)): vol.Coerce(float),
                vol.Required(CONF_ECO_OUTDOOR_OFF, default=_num(CONF_ECO_OUTDOOR_OFF, DEFAULT_ECO_OUTDOOR_OFF)): vol.Coerce(float),
                vol.Required(CONF_SUMMER_THRESHOLD, default=_num(CONF_SUMMER_THRESHOLD, DEFAULT_SUMMER_THRESHOLD)): vol.Coerce(float),
                vol.Required(CONF_OVERRIDE_MINUTES, default=_num(CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES)): vol.Coerce(int),
                vol.Required(CONF_MORNING_OFF_START, default=_num(CONF_MORNING_OFF_START, DEFAULT_MORNING_OFF_START)): selector.TimeSelector(),
                vol.Required(CONF_DAY_START, default=_num(CONF_DAY_START, DEFAULT_DAY_START)): selector.TimeSelector(),
                vol.Required(CONF_NIGHT_START, default=_num(CONF_NIGHT_START, DEFAULT_NIGHT_START)): selector.TimeSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
