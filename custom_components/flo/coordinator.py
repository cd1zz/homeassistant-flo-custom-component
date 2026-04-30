"""Flo coordinators.

A single :class:`FloLocationDataUpdateCoordinator` polls every 60s per Flo
location and fetches *presence*, *consumption*, and *all device states* in one
batch. Each device is then represented by a passive
:class:`FloDeviceDataUpdateCoordinator` that subscribes to the location
coordinator and exposes the same property API the entity layer already
consumes — so the change is transparent to ``entity.py``, ``sensor.py``,
``binary_sensor.py``, and ``switch.py``.

This replaces the previous design where every device owned its own polling
``DataUpdateCoordinator``. With N devices that pattern produced ~3·N+1
requests per minute against api-gw.meetflo.com (a stampede that hit Moen's
rate limits for users with many leak detectors).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from json import JSONDecodeError
from typing import Any, TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from .api import FloAPI

type FloConfigEntry = ConfigEntry[FloRuntimeData]


@dataclass
class FloRuntimeData:
    """Flo runtime data."""

    client: FloAPI
    devices: list[FloDeviceDataUpdateCoordinator]
    locations: list[FloLocationDataUpdateCoordinator] = field(default_factory=list)


class FloLocationDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Single coordinator per Flo location.

    Polls once per minute and stores::

        {
            "devices": {device_id: device_info_dict, ...},
            "consumption": {...},
        }
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api_client: FloAPI,
        location_id: str,
        device_ids: list[str],
    ) -> None:
        """Initialize the location coordinator."""
        self.api_client: FloAPI = api_client
        self._flo_location_id: str = location_id
        self._device_ids: list[str] = list(device_ids)
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-location-{location_id}",
            update_interval=timedelta(seconds=60),
        )

    @property
    def location_id(self) -> str:
        """Return Flo location id."""
        return self._flo_location_id

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch presence ping, consumption, and all device states in one batch."""
        from .api import FloAuthError, FloRequestError

        try:
            async with asyncio.timeout(30):
                presence_task = self._safe_presence()
                consumption_task = self._safe_consumption()
                device_tasks = [
                    self.api_client.get_device_info(device_id)
                    for device_id in self._device_ids
                ]
                results = await asyncio.gather(
                    presence_task,
                    consumption_task,
                    *device_tasks,
                    return_exceptions=True,
                )
        except FloAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except (FloRequestError, TimeoutError, JSONDecodeError) as err:
            raise UpdateFailed(err) from err

        presence_res, consumption_res, *device_results = results

        if isinstance(presence_res, FloAuthError):
            raise ConfigEntryAuthFailed(presence_res) from presence_res

        if isinstance(consumption_res, FloAuthError):
            raise ConfigEntryAuthFailed(consumption_res) from consumption_res
        consumption = consumption_res if isinstance(consumption_res, dict) else {}
        if isinstance(consumption_res, Exception):
            LOGGER.warning("Consumption fetch failed: %s", consumption_res)

        devices: dict[str, dict[str, Any]] = {}
        prior_devices = (self.data or {}).get("devices", {})
        for device_id, res in zip(self._device_ids, device_results, strict=True):
            if isinstance(res, FloAuthError):
                raise ConfigEntryAuthFailed(res) from res
            if isinstance(res, Exception):
                LOGGER.warning("Device %s fetch failed: %s", device_id, res)
                devices[device_id] = prior_devices.get(device_id, {})
                continue
            devices[device_id] = res

        # If *every* device fetch failed and we have no prior data, treat as
        # an UpdateFailed so HA marks entities unavailable instead of cheerful.
        any_fresh = any(
            not isinstance(r, Exception) for r in device_results
        )
        if not any_fresh and not prior_devices:
            raise UpdateFailed("All device fetches failed")

        return {"devices": devices, "consumption": consumption}

    async def _safe_presence(self) -> Any:
        """Send presence ping; swallow non-auth errors (it's best-effort)."""
        from .api import FloAuthError, FloRequestError

        try:
            return await self.api_client.send_presence_ping()
        except FloAuthError:
            raise
        except (FloRequestError, TimeoutError) as err:
            LOGGER.debug("Presence ping failed (non-critical): %s", err)
            return err

    async def _safe_consumption(self) -> Any:
        """Fetch today's consumption; let auth errors bubble up."""
        from .api import FloAuthError, FloRequestError

        now = dt_util.now()
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now.replace(hour=23, minute=59, second=59, microsecond=999000)
        try:
            return await self.api_client.get_consumption_info(
                self._flo_location_id, start_date, end_date
            )
        except FloAuthError:
            raise
        except (FloRequestError, TimeoutError) as err:
            return err


class FloDeviceDataUpdateCoordinator(DataUpdateCoordinator):
    """Passive per-device proxy onto a location coordinator.

    Does not poll. Subscribes to its parent
    :class:`FloLocationDataUpdateCoordinator` and re-emits updates to entity
    listeners with the device's slice of the batched data.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        location_coordinator: FloLocationDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the device coordinator."""
        self.api_client: FloAPI = location_coordinator.api_client
        self._location_coordinator: FloLocationDataUpdateCoordinator = (
            location_coordinator
        )
        self._flo_location_id: str = location_coordinator.location_id
        self._flo_device_id: str = device_id
        self._manufacturer: str = "Flo by Moen"
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-{device_id}",
            update_interval=None,
        )
        self._unsub_parent = location_coordinator.async_add_listener(
            self._handle_location_update
        )

    @callback
    def _handle_location_update(self) -> None:
        """Mirror the location coordinator's success/failure state to listeners."""
        parent = self._location_coordinator
        if parent.last_update_success:
            self.async_set_updated_data(self._device_information)
        else:
            self.last_update_success = False
            self.last_exception = parent.last_exception
            self.async_update_listeners()

    async def async_config_entry_first_refresh(self) -> None:
        """No independent refresh — the location coordinator did it."""
        if self._location_coordinator.last_update_success:
            self.data = self._device_information

    async def async_request_refresh(self) -> None:
        """Bubble up to the location coordinator."""
        await self._location_coordinator.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Detach from parent and shut down."""
        if self._unsub_parent is not None:
            self._unsub_parent()
            self._unsub_parent = None
        await super().async_shutdown()

    @property
    def _device_information(self) -> dict[str, Any]:
        """Return this device's slice of the location coordinator data."""
        if not self._location_coordinator.data:
            return {}
        return (
            self._location_coordinator.data.get("devices", {}).get(
                self._flo_device_id, {}
            )
        )

    @property
    def _water_usage(self) -> dict[str, Any]:
        """Return the current consumption payload from the location coordinator."""
        if not self._location_coordinator.data:
            return {}
        return self._location_coordinator.data.get("consumption", {}) or {}

    def _get_device_value(self, *keys: str, default: Any = None) -> Any:
        """Safely traverse nested dict keys in device information."""
        data: Any = self._device_information
        for key in keys:
            if not isinstance(data, dict):
                return default
            data = data.get(key)
            if data is None:
                return default
        return data

    @property
    def location_id(self) -> str:
        """Return Flo location id."""
        return self._flo_location_id

    @property
    def id(self) -> str:
        """Return Flo device id."""
        return self._flo_device_id

    @property
    def device_name(self) -> str:
        """Return device name."""
        return self._device_information.get(
            "nickname", f"{self.manufacturer} {self.model}"
        )

    @property
    def manufacturer(self) -> str:
        """Return manufacturer for device."""
        return self._manufacturer

    @property
    def mac_address(self) -> str:
        """Return MAC address for device (empty string when not yet known)."""
        return self._get_device_value("macAddress", default="")

    @property
    def model(self) -> str:
        """Return model for device."""
        return self._get_device_value("deviceModel", default="Unknown")

    @property
    def rssi(self) -> float | None:
        """Return rssi for device."""
        return self._get_device_value("connectivity", "rssi")

    @property
    def last_heard_from_time(self) -> str | None:
        """Return lastHeardFromTime for device."""
        return self._get_device_value("lastHeardFromTime")

    @property
    def device_type(self) -> str:
        """Return the device type for the device."""
        return self._get_device_value("deviceType", default="")

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        return (
            self._location_coordinator.last_update_success
            and self._get_device_value("isConnected", default=False)
        )

    @property
    def current_system_mode(self) -> str | None:
        """Return the current system mode."""
        return self._get_device_value("systemMode", "lastKnown")

    @property
    def target_system_mode(self) -> str | None:
        """Return the target system mode."""
        return self._get_device_value("systemMode", "target")

    @property
    def current_flow_rate(self) -> float | None:
        """Return current flow rate in gpm."""
        return self._get_device_value("telemetry", "current", "gpm")

    @property
    def current_psi(self) -> float | None:
        """Return the current pressure in psi."""
        return self._get_device_value("telemetry", "current", "psi")

    @property
    def temperature(self) -> float | None:
        """Return the current temperature in degrees F."""
        return self._get_device_value("telemetry", "current", "tempF")

    @property
    def humidity(self) -> float | None:
        """Return the current humidity in percent (0-100)."""
        return self._get_device_value("telemetry", "current", "humidity")

    @property
    def consumption_today(self) -> float | None:
        """Return today's consumption in gallons (location-wide)."""
        if not self._water_usage:
            return None
        aggregations = self._water_usage.get("aggregations")
        if not aggregations:
            return None
        return aggregations.get("sumTotalGallonsConsumed")

    @property
    def firmware_version(self) -> str | None:
        """Return the firmware version for the device."""
        return self._get_device_value("fwVersion")

    @property
    def serial_number(self) -> str | None:
        """Return the serial number for the device."""
        return self._get_device_value("serialNumber")

    @property
    def pending_info_alerts_count(self) -> int:
        """Return the number of pending info alerts for the device."""
        return self._get_device_value("notifications", "pending", "infoCount", default=0)

    @property
    def pending_warning_alerts_count(self) -> int:
        """Return the number of pending warning alerts for the device."""
        return self._get_device_value(
            "notifications", "pending", "warningCount", default=0
        )

    @property
    def pending_critical_alerts_count(self) -> int:
        """Return the number of pending critical alerts for the device."""
        return self._get_device_value(
            "notifications", "pending", "criticalCount", default=0
        )

    @property
    def has_alerts(self) -> bool:
        """Return True if any alert counts are greater than zero."""
        return bool(
            self.pending_info_alerts_count
            or self.pending_warning_alerts_count
            or self.pending_critical_alerts_count
        )

    @property
    def water_detected(self) -> bool:
        """Return whether water is detected, for leak detectors."""
        return self._get_device_value("fwProperties", "telemetry_water", default=False)

    @property
    def last_known_valve_state(self) -> str | None:
        """Return the last known valve state for the device."""
        return self._get_device_value("valve", "lastKnown")

    @property
    def target_valve_state(self) -> str | None:
        """Return the target valve state for the device."""
        return self._get_device_value("valve", "target")

    @property
    def battery_level(self) -> float | None:
        """Return the battery level for battery-powered device, e.g. leak detectors."""
        return self._get_device_value("battery", "level")

    async def async_set_mode_home(self) -> None:
        """Set the Flo location to home mode."""
        await self.api_client.set_location_mode(self._flo_location_id, "home")
        await self._location_coordinator.async_request_refresh()

    async def async_set_mode_away(self) -> None:
        """Set the Flo location to away mode."""
        await self.api_client.set_location_mode(self._flo_location_id, "away")
        await self._location_coordinator.async_request_refresh()

    async def async_set_mode_sleep(
        self, sleep_minutes: int, revert_to_mode: str
    ) -> None:
        """Set the Flo location to sleep mode."""
        await self.api_client.set_location_mode(
            self._flo_location_id,
            "sleep",
            revertMinutes=sleep_minutes,
            revertMode=revert_to_mode,
        )
        await self._location_coordinator.async_request_refresh()

    async def async_run_health_test(self) -> None:
        """Run a Flo device health test."""
        await self.api_client.run_health_test(self._flo_device_id)
