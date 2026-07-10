"""The Clima Smart integration: a smart brain that drives an existing climate."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_CONTROLLER, DOMAIN, PLATFORMS
from .controller import ClimaSmartController

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Clima Smart from a config entry."""
    controller = ClimaSmartController(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_CONTROLLER: controller}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-evaluate when options change (no reload needed for tuning values)."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data:
        data[DATA_CONTROLLER].async_options_updated()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data:
            await data[DATA_CONTROLLER].async_stop()
    return unload_ok
