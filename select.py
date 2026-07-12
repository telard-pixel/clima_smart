"""Operating-mode select for Clima Smart."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DATA_CONTROLLER, DOMAIN, MODES
from .entity import ClimaSmartEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id][DATA_CONTROLLER]
    async_add_entities([ClimaSmartModeSelect(controller)])


class ClimaSmartModeSelect(ClimaSmartEntity, RestoreEntity, SelectEntity):
    """Auto / Comfort / Away / Notte / Spento."""

    _attr_translation_key = "mode"
    _attr_icon = "mdi:tune-variant"
    _attr_options = MODES

    def __init__(self, controller) -> None:
        super().__init__(controller, "mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the chosen mode across HA restarts (before the first evaluate).
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in MODES:
            self._controller.mode = last_state.state
        self._controller.mark_restore_ready("mode")

    @property
    def current_option(self) -> str:
        return self._controller.mode

    async def async_select_option(self, option: str) -> None:
        await self._controller.async_set_mode(option)
