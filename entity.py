"""Shared base entity for Clima Smart."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import ClimaSmartController


class ClimaSmartEntity(Entity):
    """Base entity bound to the controller; refreshes when the brain re-evaluates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: ClimaSmartController, key: str) -> None:
        self._controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            name="Clima Smart",
            manufacturer="tis24dev",
            model="Smart climate controller",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._controller.register_update_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self._controller.unregister_update_callback(self.async_write_ha_state)
        await super().async_will_remove_from_hass()
