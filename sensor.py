"""Diagnostic sensors that show what the brain is doing."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfFrequency, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_CONTROLLER,
    DOMAIN,
    PHASE_DAY,
    PHASE_GAP,
    PHASE_NIGHT,
    PHASE_SLEEP,
    PHASE_WIND_DOWN,
)
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
            ClimaSmartHouseSensor(controller),
            ClimaSmartReasonSensor(controller),
            ClimaSmartEfficiencySensor(controller),
        ]
    )


class ClimaSmartHouseSensor(ClimaSmartEntity, SensorEntity):
    """The other rooms' average, exactly as the daytime start rule reads it.

    Deliberately the controller's own value rather than a template that redoes the
    arithmetic: if a sensor drops out, what is shown here is what actually decides.
    """

    _attr_translation_key = "house_average"
    _attr_icon = "mdi:home-thermometer-outline"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    # Senza questo il recorder non archivia nulla oltre la finestra di purge, e
    # ogni taratura resta prigioniera degli ultimi giorni: le statistiche a lungo
    # termine sono aggregati orari che sopravvivono per sempre e costano pochi
    # byte al giorno. E' la base dati di ogni confronto fra stagioni.
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, controller) -> None:
        super().__init__(controller, "house_average")

    @property
    def native_value(self) -> float | None:
        return self._controller._house_average()

    @property
    def extra_state_attributes(self) -> dict:
        ctrl = self._controller
        entities = ctrl._cfg("house_sensors") or []
        if isinstance(entities, str):
            entities = [entities]
        soglia = float(ctrl._cfg("auto_start_house", 0.0) or 0.0)
        media = ctrl._house_average()
        return {
            "sensori": list(entities),
            "soglia_avvio": soglia or None,
            "sopra_soglia": None if media is None or not soglia else media >= soglia,
        }


class ClimaSmartPhaseSensor(ClimaSmartEntity, SensorEntity):
    _attr_translation_key = "phase"
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        PHASE_DAY,
        PHASE_NIGHT,
        PHASE_SLEEP,
        PHASE_WIND_DOWN,
        PHASE_GAP,
    ]

    def __init__(self, controller) -> None:
        super().__init__(controller, "phase")

    @property
    def native_value(self) -> str | None:
        return self._controller.current_phase


class ClimaSmartTargetSensor(ClimaSmartEntity, SensorEntity):
    _attr_translation_key = "target"
    _attr_icon = "mdi:thermometer-check"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    # Come la media di casa: e' il target che il controller ha davvero scelto, la
    # traccia di cosa ha deciso l'algoritmo. Senza archivio non si puo' rigiocare
    # una giornata a distanza di mesi.
    _attr_state_class = SensorStateClass.MEASUREMENT
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
            "innesco": ctrl.last_trigger,
            "valutato_alle": ctrl.last_evaluated.isoformat()
            if ctrl.last_evaluated
            else None,
        }


class ClimaSmartEfficiencySensor(ClimaSmartEntity, SensorEntity):
    """Hz impliciti dalla potenza Shelly: l'unica finestra rimasta sul
    compressore da quando il sensore di frequenza e' stato disabilitato.

    Vuoto (None) quando non si puo' stimare in modo onesto: macchina non in
    raffrescamento/deumidificazione, wattmetro non collegato, o potenza sotto
    la soglia dei 28 Hz dove la curva misurata non vale piu'.
    """

    _attr_translation_key = "efficiency"
    _attr_icon = "mdi:sine-wave"
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 1

    def __init__(self, controller) -> None:
        super().__init__(controller, "efficiency")

    @property
    def native_value(self) -> float | None:
        return self._controller.implied_compressor_hz

    @property
    def extra_state_attributes(self) -> dict:
        ctrl = self._controller
        return {
            "w_misurati": ctrl.efficiency_measured_watts,
            "stima_affidabile": ctrl.efficiency_reliable,
            "in_fascia_efficiente": ctrl.efficiency_in_band,
            "estrapolato_oltre_81hz": ctrl.efficiency_extrapolated,
            "resa_scarsa_da_minuti": round(ctrl.poor_efficiency_minutes, 1),
            "resa_scarsa_prolungata": ctrl.poor_efficiency_alert,
        }
