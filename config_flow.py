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
    CONF_PRESENCE_HOME_STATE,
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
    DEFAULT_PRESENCE_HOME_STATE,
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


def _time_to_minutes(value: str) -> int:
    hh, mm = str(value).split(":")[:2]
    return int(hh) * 60 + int(mm)


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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the linked entities be swapped (e.g. climate/switch replaced or
        renamed) without losing the tuned options, which live separately.
        """
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            # Re-derive the unique_id so swapping to a different climate still
            # blocks a second entry from managing the same climate (and frees
            # up the previous climate_entity for a future entry).
            await self.async_set_unique_id(user_input[CONF_CLIMATE])
            self._abort_if_unique_id_configured()
            return self.async_update_reload_and_abort(entry, data=user_input)

        return self.async_show_form(
            step_id="reconfigure", data_schema=_setup_schema(entry.data)
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
        opts = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}

        if user_input is not None:
            morning = _time_to_minutes(user_input[CONF_MORNING_OFF_START])
            day = _time_to_minutes(user_input[CONF_DAY_START])
            night = _time_to_minutes(user_input[CONF_NIGHT_START])
            if not (morning < day < night):
                errors["base"] = "invalid_time_order"
            # eco_outdoor_on must stay below eco_outdoor_off: _eco_decision checks
            # the "on" condition first, so a swapped/equal pair makes the "off"
            # branch practically unreachable and eco silently gets stuck on.
            elif user_input[CONF_ECO_OUTDOOR_ON] >= user_input[CONF_ECO_OUTDOOR_OFF]:
                errors["base"] = "invalid_eco_range"
            else:
                return self.async_create_entry(title="", data=user_input)
            # Re-show the form with what the user just typed, not the old values.
            opts = {**opts, **user_input}

        def _num(key, default):
            return opts.get(key, default)

        # Bounds mirror the corresponding TuneNumber entries in number.py so the
        # options flow can't put the controller into a state the number UI
        # itself would never allow (e.g. a negative override, or an eco/target
        # temperature nobody could reach).
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARGET_HOME, default=_num(CONF_TARGET_HOME, DEFAULT_TARGET_HOME)
                ): vol.All(vol.Coerce(float), vol.Range(min=16, max=30)),
                vol.Required(
                    CONF_TARGET_AWAY, default=_num(CONF_TARGET_AWAY, DEFAULT_TARGET_AWAY)
                ): vol.All(vol.Coerce(float), vol.Range(min=16, max=30)),
                vol.Required(
                    CONF_ECO_BAND, default=_num(CONF_ECO_BAND, DEFAULT_ECO_BAND)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5)),
                vol.Required(
                    CONF_ECO_OUTDOOR_ON, default=_num(CONF_ECO_OUTDOOR_ON, DEFAULT_ECO_OUTDOOR_ON)
                ): vol.All(vol.Coerce(float), vol.Range(min=20, max=45)),
                vol.Required(
                    CONF_ECO_OUTDOOR_OFF, default=_num(CONF_ECO_OUTDOOR_OFF, DEFAULT_ECO_OUTDOOR_OFF)
                ): vol.All(vol.Coerce(float), vol.Range(min=20, max=45)),
                vol.Required(
                    CONF_SUMMER_THRESHOLD, default=_num(CONF_SUMMER_THRESHOLD, DEFAULT_SUMMER_THRESHOLD)
                ): vol.All(vol.Coerce(float), vol.Range(min=10, max=30)),
                vol.Required(
                    CONF_OVERRIDE_MINUTES, default=_num(CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES)
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=480)),
                vol.Required(CONF_MORNING_OFF_START, default=_num(CONF_MORNING_OFF_START, DEFAULT_MORNING_OFF_START)): selector.TimeSelector(),
                vol.Required(CONF_DAY_START, default=_num(CONF_DAY_START, DEFAULT_DAY_START)): selector.TimeSelector(),
                vol.Required(CONF_NIGHT_START, default=_num(CONF_NIGHT_START, DEFAULT_NIGHT_START)): selector.TimeSelector(),
                vol.Required(CONF_PRESENCE_HOME_STATE, default=_num(CONF_PRESENCE_HOME_STATE, DEFAULT_PRESENCE_HOME_STATE)): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
