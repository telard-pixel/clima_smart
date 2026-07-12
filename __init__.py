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

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await controller.async_start()
    except Exception:
        await controller.async_stop()
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on linked-entity changes; re-evaluate lightweight tuning changes."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data:
        controller = data[DATA_CONTROLLER]
        if controller.config_data_changed:
            await hass.config_entries.async_reload(entry.entry_id)
        else:
            controller.async_options_updated()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    controller = data[DATA_CONTROLLER] if data else None
    was_enabled = controller.enabled if controller else False
    if controller:
        # Stop new commands during platform teardown, but keep the controller
        # restartable if Home Assistant reports that unloading failed.
        await controller.async_pause()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if controller:
            await controller.async_stop()
    elif controller:
        controller.enabled = was_enabled
        controller.async_options_updated()
    return unload_ok
