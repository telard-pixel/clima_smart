"""Runtime tuning numbers for Clima Smart (persisted into entry options)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ECO_BAND,
    CONF_ECO_OUTDOOR_OFF,
    CONF_ECO_OUTDOOR_ON,
    CONF_OVERRIDE_MINUTES,
    CONF_SETPOINT_OFFSET,
    CONF_SUMMER_THRESHOLD,
    CONF_TARGET_HOME,
    CONF_TARGET_SLEEP,
    CONF_WINTER_HOUSE_CEILING,
    CONF_WINTER_ROOM_START,
    CONF_WINTER_ROOM_TARGET,
    DATA_CONTROLLER,
    DEFAULT_ECO_BAND,
    DEFAULT_ECO_OUTDOOR_OFF,
    DEFAULT_ECO_OUTDOOR_ON,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_SETPOINT_OFFSET,
    DEFAULT_SUMMER_THRESHOLD,
    DEFAULT_TARGET_HOME,
    DEFAULT_TARGET_SLEEP,
    DEFAULT_WINTER_HOUSE_CEILING,
    DEFAULT_WINTER_ROOM_START,
    DEFAULT_WINTER_ROOM_TARGET,
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
    # Deliberately absent on the setpoint correction: it is a difference, and a
    # temperature device class would convert it as if it were an absolute reading.
    device_class: str | None = None


_NUMBERS: tuple[TuneNumber, ...] = (
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_TARGET_HOME, default=DEFAULT_TARGET_HOME,
               minimum=16, maximum=30, step=0.5, icon="mdi:home-thermometer",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_TARGET_SLEEP, default=DEFAULT_TARGET_SLEEP,
               minimum=16, maximum=30, step=0.5, icon="mdi:bed",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_SETPOINT_OFFSET, default=DEFAULT_SETPOINT_OFFSET,
               minimum=-3, maximum=3, step=0.5, icon="mdi:tune-vertical",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_ECO_BAND, default=DEFAULT_ECO_BAND,
               minimum=0.5, maximum=5, step=0.5, icon="mdi:leaf",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_ECO_OUTDOOR_ON, default=DEFAULT_ECO_OUTDOOR_ON,
               minimum=20, maximum=45, step=1, icon="mdi:weather-sunny",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_ECO_OUTDOOR_OFF, default=DEFAULT_ECO_OUTDOOR_OFF,
               minimum=20, maximum=45, step=1, icon="mdi:weather-sunny-alert",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_SUMMER_THRESHOLD, default=DEFAULT_SUMMER_THRESHOLD,
               minimum=10, maximum=30, step=1, icon="mdi:sun-thermometer",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(key=CONF_OVERRIDE_MINUTES, default=DEFAULT_OVERRIDE_MINUTES,
               minimum=0, maximum=480, step=5, icon="mdi:hand-back-right",
               unit=UnitOfTime.MINUTES, device_class=NumberDeviceClass.DURATION),
    # Le tre dell'inverno, accanto alle estive: `target_home` e `target_sleep`
    # erano gia' manopole rapide, le loro corrispondenti invernali stavano
    # sepolte in un modulo di trentaquattro campi. Stessa cosa, stesso posto.
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_WINTER_ROOM_START,
               default=DEFAULT_WINTER_ROOM_START,
               minimum=0, maximum=30, step=0.5, icon="mdi:radiator",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_WINTER_ROOM_TARGET,
               default=DEFAULT_WINTER_ROOM_TARGET,
               minimum=0, maximum=30, step=0.5, icon="mdi:thermometer-chevron-up",
               unit=UnitOfTemperature.CELSIUS),
    TuneNumber(device_class=NumberDeviceClass.TEMPERATURE, key=CONF_WINTER_HOUSE_CEILING,
               default=DEFAULT_WINTER_HOUSE_CEILING,
               minimum=0, maximum=30, step=0.5, icon="mdi:home-thermometer-outline",
               unit=UnitOfTemperature.CELSIUS),
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
        self._attr_device_class = desc.device_class
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float:
        entry = self._controller.entry
        if self._desc.key in entry.options:
            return float(entry.options[self._desc.key])
        return float(entry.data.get(self._desc.key, self._desc.default))

    def _winter_option(self, key: str, default: float) -> float:
        """L'altra soglia della coppia invernale, come la legge il controller.

        Non c'e' una proprieta' sul controller per queste due - le legge dalle
        opzioni al momento di decidere - quindi qui si guarda nello stesso
        posto, invece di aggiungere due proprieta' usate solo da questa guardia.
        """
        entry = self._controller.entry
        grezzo = entry.options.get(key, entry.data.get(key, default))
        try:
            return float(grezzo)
        except (TypeError, ValueError):
            return float(default)

    async def async_set_native_value(self, value: float) -> None:
        entry = self._controller.entry
        if (
            self._desc.key == CONF_ECO_OUTDOOR_ON
            and value >= self._controller.eco_outdoor_off
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="eco_on_not_below_off"
            )
        if (
            self._desc.key == CONF_ECO_OUTDOOR_OFF
            and value <= self._controller.eco_outdoor_on
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="eco_off_not_above_on"
            )
        # Stessa guardia della coppia eco, per la coppia invernale: soglie
        # incrociate o uguali farebbero accendere e spegnere il compressore a
        # ogni passata. Il controller si difende gia' da solo trattandole come
        # "non configurate", ma dirlo qui e' onesto: chi gira la manopola vede
        # perche' quel valore non va, invece di trovarsi la funzione muta.
        # Lo zero resta libero in entrambe: e' il modo di disattivare.
        if self._desc.key == CONF_WINTER_ROOM_START:
            tetto = self._winter_option(CONF_WINTER_ROOM_TARGET, DEFAULT_WINTER_ROOM_TARGET)
            if value > 0 and tetto > 0 and value >= tetto:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="winter_start_not_below_target",
                )
        if self._desc.key == CONF_WINTER_ROOM_TARGET:
            avvio = self._winter_option(CONF_WINTER_ROOM_START, DEFAULT_WINTER_ROOM_START)
            if value > 0 and avvio > 0 and value <= avvio:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="winter_target_not_above_start",
                )
        options = dict(entry.options)
        options[self._desc.key] = value
        # Triggers the update listener -> controller re-evaluates.
        self.hass.config_entries.async_update_entry(entry, options=options)
