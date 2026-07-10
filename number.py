"""Runtime tuning numbers for Clima Smart (persisted into entry options)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ECO_BAND,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_OVERRIDE_MINUTES,
    CONF_SUMMER_THRESHOLD,
    CONF_TARGET_AWAY,
    CONF_TARGET_HOME,
    DATA_CONTROLLER,
    DEFAULT_ECO_BAND,
    DEFAULT_ECO_OUTDOOR_OFF,
    DEFAULT_ECO_OUTDOOR_ON,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_SUMMER_THRESHOLD,
    DEFAULT_TARGET_AWAY,
    DEFAULT_TARGET_HOME,
    DOMAIN,
)
from .entity import ClimaSmartEntity


@dataclass(frozen=True, kw_only=True)
class TuneNumber:
    key: str
    default: float
    minimum: float
    maximum: float
    step: float
    icon: str
    unit: str | None = None


_NUMBERS: tuple[TuneNumber, ...] = (
    TuneNumber(key=CONF_TARGET_HOME, default=DEFAULT_TARGET_HOME,
               minimum=16, maximum=30, step=0.5, icon="mdi:home-thermometer",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_TARGET_AWAY, default=DEFAULT_TARGET_AWAY,
               minimum=16, maximum=30, step=0.5, icon="mdi:home-export-outline",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_ECO_BAND, default=DEFAULT_ECO_BAND,
               minimum=0.5, maximum=5, step=0.5, icon="mdi:leaf",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_ECO_OUTDOOR_ON, default=DEFAULT_ECO_OUTDOOR_ON,
               minimum=20, maximum=45, step=1, icon="mdi:weather-sunny",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_ECO_OUTDOOR_OFF, default=DEFAULT_ECO_OUTDOOR_OFF,
               minimum=20, maximum=45, step=1, icon="mdi:weather-sunny-alert",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_SUMMER_THRESHOLD, default=DEFAULT_SUMMER_THRESHOLD,
               minimum=10, maximum=30, step=1, icon="mdi:sun-thermometer",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_OVERRIDE_MINUTES, default=DEFAULT_OVERRIDE_MINUTES,
               minimum=0, maximum=480, step=5, icon="mdi:hand-back-right", unit="min"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id][DATA_CONTROLLER]
    async_add_entities(ClimaSmartNumber(controller, desc) for desc in _NUMBERS)


class ClimaSmartNumber(ClimaSmartEntity, NumberEntity):
    """A tunable value stored in the config entry options."""

    _attr_mode = NumberMode.BOX

    def __init__(self, controller, desc: TuneNumber) -> None:
        super().__init__(controller, desc.key)
        self._desc = desc
        self._attr_translation_key = desc.key
        self._attr_icon = desc.icon
        self._attr_native_min_value = desc.minimum
        self._attr_native_max_value = desc.maximum
        self._attr_native_step = desc.step
        self._attr_native_unit_of_measurement = desc.unit
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float:
        entry = self._controller.entry
        if self._desc.key in entry.options:
            return float(entry.options[self._desc.key])
        return float(entry.data.get(self._desc.key, self._desc.default))

    async def async_set_native_value(self, value: float) -> None:
        entry = self._controller.entry
        options = dict(entry.options)
        options[self._desc.key] = value
        # Triggers the update listener -> controller re-evaluates.
        self.hass.config_entries.async_update_entry(entry, options=options)
