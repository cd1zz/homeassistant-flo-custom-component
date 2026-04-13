"""Base entity class for Flo entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FloDeviceDataUpdateCoordinator


class FloEntity(CoordinatorEntity[FloDeviceDataUpdateCoordinator]):
    """A base class for Flo entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entity_type: str,
        device: FloDeviceDataUpdateCoordinator,
        **kwargs,
    ) -> None:
        """Init Flo entity."""
        super().__init__(device)
        self._attr_unique_id = f"{device.mac_address}_{entity_type}"
        self._device: FloDeviceDataUpdateCoordinator = device

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        return DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self._device.mac_address)},
            identifiers={(DOMAIN, self._device.id)},
            serial_number=self._device.serial_number,
            manufacturer=self._device.manufacturer,
            model=self._device.model,
            name=self._device.device_name.capitalize(),
            sw_version=self._device.firmware_version,
        )

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        return super().available and self._device.available
