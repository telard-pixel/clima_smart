"""Diagnostic sensors that show what the brain is doing."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_CONTROLLER, DOMAIN
from .entity import ClimaSmartEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id][DATA_CONTROLLER]
    async_add_entities(
        [
            ClimaSmartPhaseSensor(controller),
            ClimaSmartTargetSensor(controller),
            ClimaSmartReasonSensor(controller),
        ]
    )


class ClimaSmartPhaseSensor(ClimaSmartEntity, SensorEntity):
    _attr_translation_key = "phase"
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller) -> None:
        super().__init__(controller, "phase")

    @property
    def native_value(self) -> str | None:
        return self._controller.current_phase


class ClimaSmartTargetSensor(ClimaSmartEntity, SensorEntity):
    _attr_translation_key = "target"
    _attr_icon = "mdi:thermometer-check"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller) -> None:
        super().__init__(controller, "target")

    @property
    def native_value(self) -> float | None:
        return self._controller.active_target


class ClimaSmartReasonSensor(ClimaSmartEntity, SensorEntity):
    _attr_translation_key = "reason"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller) -> None:
        super().__init__(controller, "reason")

    @property
    def native_value(self) -> str | None:
        # Truncate to the state length limit (255 chars).
        return (self._controller.last_reason or "")[:255]

    @property
    def extra_state_attributes(self) -> dict:
        ctrl = self._controller
        return {
            "abilitato": ctrl.enabled,
            "modo": ctrl.mode,
            "override_attivo": ctrl.override_active,
            "override_fino_a": ctrl.override_until.isoformat()
            if ctrl.override_until
            else None,
        }
