"""The flo integration."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import FloAuthError, FloRequestError, async_get_api
from .coordinator import (
    FloConfigEntry,
    FloDeviceDataUpdateCoordinator,
    FloLocationDataUpdateCoordinator,
    FloRuntimeData,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: FloConfigEntry) -> bool:
    """Set up flo from a config entry."""
    try:
        client = await async_get_api(
            hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
    except FloAuthError as err:
        raise ConfigEntryAuthFailed from err
    except FloRequestError as err:
        raise ConfigEntryNotReady from err

    try:
        account_locations = await client.get_locations()
    except FloAuthError as err:
        raise ConfigEntryAuthFailed from err
    except FloRequestError as err:
        raise ConfigEntryNotReady from err

    locations: list[FloLocationDataUpdateCoordinator] = []
    devices: list[FloDeviceDataUpdateCoordinator] = []
    for location in account_locations:
        device_ids = [device["id"] for device in location["devices"]]
        if not device_ids:
            continue
        location_coordinator = FloLocationDataUpdateCoordinator(
            hass, entry, client, location["id"], device_ids
        )
        locations.append(location_coordinator)
        devices.extend(
            FloDeviceDataUpdateCoordinator(
                hass, entry, location_coordinator, device_id
            )
            for device_id in device_ids
        )

    await asyncio.gather(
        *(loc.async_config_entry_first_refresh() for loc in locations)
    )
    for device in devices:
        await device.async_config_entry_first_refresh()

    entry.runtime_data = FloRuntimeData(
        client=client, devices=devices, locations=locations
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: FloConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        for device in entry.runtime_data.devices:
            await device.async_shutdown()
        for location in entry.runtime_data.locations:
            await location.async_shutdown()
    return unloaded
