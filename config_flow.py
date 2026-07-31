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

from .validation import (
    aux_switches_are_distinct,
    normalise_presence_state,
    validate_options,
)
from .const import (
    CONF_AUTO_START_ROOM,
    CONF_AUTO_START_SLEEP,
    CONF_CLIMATE,
    CONF_DAY_START,
    CONF_ECO_BAND,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_ECO_SWITCH,
    CONF_HUMIDITY,
    CONF_MORNING_OFF_START,
    CONF_MUTE_SWITCH,
    CONF_NIGHT_START,
    CONF_NIGHT_SWITCH,
    CONF_OUTDOOR,
    CONF_OUTDOOR_FALLBACK,
    CONF_OVERRIDE_MINUTES,
    CONF_PRESENCE,
    CONF_PRESENCE_HOME_STATE,
    CONF_SETPOINT_OFFSET,
    CONF_SLEEP_END,
    CONF_SLEEP_START,
    CONF_SUMMER_THRESHOLD,
    CONF_TARGET_AWAY,
    CONF_TARGET_HOME,
    CONF_TARGET_SLEEP,
    DEFAULT_AUTO_START_ROOM,
    DEFAULT_AUTO_START_SLEEP,
    DEFAULT_DAY_START,
    DEFAULT_ECO_BAND,
    DEFAULT_ECO_OUTDOOR_OFF,
    DEFAULT_ECO_OUTDOOR_ON,
    DEFAULT_MORNING_OFF_START,
    DEFAULT_NIGHT_START,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_PRESENCE_HOME_STATE,
    DEFAULT_SETPOINT_OFFSET,
    DEFAULT_SLEEP_END,
    DEFAULT_SLEEP_START,
    DEFAULT_SUMMER_THRESHOLD,
    DEFAULT_TARGET_AWAY,
    DEFAULT_TARGET_HOME,
    DEFAULT_TARGET_SLEEP,
    DOMAIN,
)


def _entity(
    domain: str | list[str], *, device_class: str | None = None
) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    )


def _optional(key: str, defaults: dict[str, Any]) -> vol.Optional:
    """An optional field that can also be emptied.

    With `default=` voluptuous quietly puts the previous value back whenever the
    field arrives empty, so an entity linked once could never be unlinked from the
    form again: clearing "Modalità notte" and saving left it exactly where it was.
    A suggested value pre-fills the form the same way, but an empty field really
    does come back empty.
    """
    return vol.Optional(key, description={"suggested_value": defaults.get(key)})


def _setup_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CLIMATE, default=defaults.get(CONF_CLIMATE)): _entity(
                "climate"
            ),
            _optional(CONF_PRESENCE, defaults): _entity(["device_tracker", "person"]),
            _optional(CONF_OUTDOOR, defaults): _entity(
                "sensor", device_class="temperature"
            ),
            _optional(CONF_OUTDOOR_FALLBACK, defaults): _entity(
                "sensor", device_class="temperature"
            ),
            _optional(CONF_HUMIDITY, defaults): _entity(
                "sensor", device_class="humidity"
            ),
            _optional(CONF_ECO_SWITCH, defaults): _entity("switch"),
            _optional(CONF_MUTE_SWITCH, defaults): _entity("switch"),
            _optional(CONF_NIGHT_SWITCH, defaults): _entity("switch"),
        }
    )


def _aux_switches_are_distinct(values: dict[str, Any]) -> bool:
    """Kept as a thin alias: the rule itself lives in `validation`, which has no
    Home Assistant or voluptuous import and can therefore be tested directly."""
    return aux_switches_are_distinct(values)


class ClimaSmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if _aux_switches_are_distinct(user_input):
                climate_entity = user_input[CONF_CLIMATE]
                await self.async_set_unique_id(climate_entity)
                self._abort_if_unique_id_configured(reload_on_update=False)
                # Also cover entries created by an older release without a
                # unique_id, or whose unique_id predates a reconfiguration.
                self._async_abort_entries_match({CONF_CLIMATE: climate_entity})
                return self.async_create_entry(title="Clima Smart", data=user_input)
            return self.async_show_form(
                step_id="user",
                data_schema=_setup_schema(user_input),
                errors={"base": "duplicate_aux_switch"},
            )

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
            if not _aux_switches_are_distinct(user_input):
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_setup_schema(user_input),
                    errors={"base": "duplicate_aux_switch"},
                )
            # The linked climate is also our unique id. Permit this entry to keep
            # or change it, but never let it take over a climate managed by a
            # different Clima Smart entry.
            new_climate = user_input[CONF_CLIMATE]
            duplicate = next(
                (
                    candidate
                    for candidate in self._async_current_entries()
                    if candidate.entry_id != entry.entry_id
                    and (
                        candidate.data.get(CONF_CLIMATE) == new_climate
                        or candidate.unique_id == new_climate
                    )
                ),
                None,
            )
            if duplicate is not None:
                # Il form torna con l'errore invece di chiudersi: abortire buttava
                # via tutto quello che l'utente aveva appena compilato.
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_setup_schema(user_input),
                    errors={"base": "already_configured"},
                )

            # The update listener performs the one required reload when entry.data
            # changes. Using the non-reloading helper avoids the double-reload race
            # deprecated by Home Assistant 2026.6.
            return self.async_update_and_abort(
                entry,
                unique_id=new_climate,
                data=user_input,
            )

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
            problem = validate_options(user_input)
            if problem is None:
                user_input[CONF_PRESENCE_HOME_STATE] = normalise_presence_state(
                    user_input[CONF_PRESENCE_HOME_STATE]
                )
                return self.async_create_entry(title="", data=user_input)
            errors["base"] = problem
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
                vol.Required(
                    CONF_TARGET_SLEEP, default=_num(CONF_TARGET_SLEEP, DEFAULT_TARGET_SLEEP)
                ): vol.All(vol.Coerce(float), vol.Range(min=16, max=30)),
                vol.Required(
                    CONF_SETPOINT_OFFSET,
                    default=_num(CONF_SETPOINT_OFFSET, DEFAULT_SETPOINT_OFFSET),
                ): vol.All(vol.Coerce(float), vol.Range(min=-3, max=3)),
                vol.Required(
                    CONF_AUTO_START_ROOM,
                    default=_num(CONF_AUTO_START_ROOM, DEFAULT_AUTO_START_ROOM),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=35)),
                vol.Required(
                    CONF_AUTO_START_SLEEP,
                    default=_num(CONF_AUTO_START_SLEEP, DEFAULT_AUTO_START_SLEEP),
                ): bool,
                vol.Required(CONF_SLEEP_START, default=_num(CONF_SLEEP_START, DEFAULT_SLEEP_START)): selector.TimeSelector(),
                vol.Required(CONF_SLEEP_END, default=_num(CONF_SLEEP_END, DEFAULT_SLEEP_END)): selector.TimeSelector(),
                vol.Required(CONF_MORNING_OFF_START, default=_num(CONF_MORNING_OFF_START, DEFAULT_MORNING_OFF_START)): selector.TimeSelector(),
                vol.Required(CONF_DAY_START, default=_num(CONF_DAY_START, DEFAULT_DAY_START)): selector.TimeSelector(),
                vol.Required(CONF_NIGHT_START, default=_num(CONF_NIGHT_START, DEFAULT_NIGHT_START)): selector.TimeSelector(),
                vol.Required(CONF_PRESENCE_HOME_STATE, default=_num(CONF_PRESENCE_HOME_STATE, DEFAULT_PRESENCE_HOME_STATE)): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
