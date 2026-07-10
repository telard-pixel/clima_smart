"""Master enable switch for Clima Smart."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DATA_CONTROLLER, DOMAIN
from .entity import ClimaSmartEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id][DATA_CONTROLLER]
    async_add_entities([ClimaSmartMasterSwitch(controller)])


class ClimaSmartMasterSwitch(ClimaSmartEntity, RestoreEntity, SwitchEntity):
    """Turns the smart control on/off (off = full manual control of the climate)."""

    _attr_translation_key = "master"
    _attr_icon = "mdi:robot"

    def __init__(self, controller) -> None:
        super().__init__(controller, "master")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the master state so an HA restart does not silently re-enable
        # control of the real climate. Runs before the controller's first evaluate.
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._controller.enabled = last_state.state == "on"

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._controller.async_set_enabled(False)
