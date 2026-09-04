"""The Clima Smart integration: a smart brain that drives an existing climate."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_HVAC_MODE,
    DATA_CONTROLLER,
    DOMAIN,
    HVAC_COOL,
    HVAC_OFF,
    PLATFORMS,
    SERVICE_BOT_COMMAND,
)
from .controller import ClimaSmartController

_LOGGER = logging.getLogger(__name__)

SERVICE_BOT_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required(ATTR_HVAC_MODE): vol.In([HVAC_OFF, HVAC_COOL]),
    }
)


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Un solo servizio a livello di dominio, condiviso da tutte le istanze

    (una per unita' climatizzata): senza la guardia su `has_service`, ogni
    config entry in piu' lo riregistrerebbe da capo.
    """
    if hass.services.has_service(DOMAIN, SERVICE_BOT_COMMAND):
        return

    async def _handle_bot_command(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        hvac_mode = call.data[ATTR_HVAC_MODE]
        for data in hass.data.get(DOMAIN, {}).values():
            controller: ClimaSmartController = data[DATA_CONTROLLER]
            if controller.climate_entity == entity_id:
                await controller.async_bot_command(hvac_mode)
                return
        _LOGGER.warning(
            "Clima Smart: comando_bot per %s, nessun controller la governa",
            entity_id,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_BOT_COMMAND,
        _handle_bot_command,
        schema=SERVICE_BOT_COMMAND_SCHEMA,
    )


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

    await _async_setup_services(hass)

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
        if not hass.data.get(DOMAIN):
            # L'ultima istanza se n'e' andata: il servizio non avrebbe piu'
            # nessun controller da servire.
            hass.services.async_remove(DOMAIN, SERVICE_BOT_COMMAND)
        if controller:
            await controller.async_stop()
    elif controller:
        controller.enabled = was_enabled
        controller.async_options_updated()
    return unload_ok
