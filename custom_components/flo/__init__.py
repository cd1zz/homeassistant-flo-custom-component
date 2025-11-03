"""The flo integration."""

import asyncio
import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import FloAuthError, FloRequestError, async_get_api
from .coordinator import FloConfigEntry, FloDeviceDataUpdateCoordinator, FloRuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: FloConfigEntry) -> bool:
    """Set up flo from a config entry."""
    try:
        client = await async_get_api(
            hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
    except FloAuthError as err:
        _LOGGER.error("Authentication failed: %s", err)
        raise ConfigEntryNotReady from err
    except FloRequestError as err:
        _LOGGER.error("Failed to connect to Flo API: %s", err)
        raise ConfigEntryNotReady from err

    try:
        user_info = await client.get_user_info(include_locations=True)
    except FloRequestError as err:
        _LOGGER.error("Failed to fetch user info: %s", err)
        raise ConfigEntryNotReady from err

    _LOGGER.debug("Flo user information with locations: %s", user_info)

    devices = [
        FloDeviceDataUpdateCoordinator(
            hass, entry, client, location["id"], device["id"]
        )
        for location in user_info["locations"]
        for device in location["devices"]
    ]

    try:
        tasks = [device.async_refresh() for device in devices]
        await asyncio.gather(*tasks)
    except FloRequestError as err:
        _LOGGER.error("Failed to refresh device data: %s", err)
        raise ConfigEntryNotReady from err

    entry.runtime_data = FloRuntimeData(client=client, devices=devices)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: FloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
