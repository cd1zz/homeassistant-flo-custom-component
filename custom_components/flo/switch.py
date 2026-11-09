"""Switch representing the shutoff valve for the Flo by Moen integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import FLO_AWAY, FLO_HOME
from .coordinator import FloConfigEntry, FloDeviceDataUpdateCoordinator
from .entity import FloEntity

# Sleep mode options (in minutes)
SLEEP_MINUTE_OPTIONS = [60, 120, 180, 240, 300, 360, 420, 480, 540, 600, 660, 720]
# System mode constants
SYSTEM_MODE_HOME = FLO_HOME
SYSTEM_REVERT_MODES = [FLO_HOME, FLO_AWAY]

ATTR_REVERT_TO_MODE = "revert_to_mode"
ATTR_SLEEP_MINUTES = "sleep_minutes"
SERVICE_SET_SLEEP_MODE = "set_sleep_mode"
SERVICE_SET_AWAY_MODE = "set_away_mode"
SERVICE_SET_HOME_MODE = "set_home_mode"
SERVICE_RUN_HEALTH_TEST = "run_health_test"

# How long after a command issued from Home Assistant the switch keeps showing the
# commanded state while waiting for the device to report the move. Slightly more
# than one 60 second poll cycle.
COMMAND_GRACE_PERIOD = timedelta(seconds=90)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Flo switches from config entry."""
    devices = config_entry.runtime_data.devices

    async_add_entities(
        [FloSwitch(device) for device in devices if device.device_type != "puck_oem"]
    )

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_SET_AWAY_MODE, None, "async_set_mode_away"
    )
    platform.async_register_entity_service(
        SERVICE_SET_HOME_MODE, None, "async_set_mode_home"
    )
    platform.async_register_entity_service(
        SERVICE_RUN_HEALTH_TEST, None, "async_run_health_test"
    )
    platform.async_register_entity_service(
        SERVICE_SET_SLEEP_MODE,
        {
            vol.Required(ATTR_SLEEP_MINUTES, default=120): vol.All(
                vol.Coerce(int),
                vol.In(SLEEP_MINUTE_OPTIONS),
            ),
            vol.Required(ATTR_REVERT_TO_MODE, default=SYSTEM_MODE_HOME): vol.In(
                SYSTEM_REVERT_MODES
            ),
        },
        "async_set_mode_sleep",
    )


class FloSwitch(FloEntity, SwitchEntity):
    """Switch class for the Flo by Moen valve."""

    _attr_translation_key = "shutoff_valve"

    def __init__(self, device: FloDeviceDataUpdateCoordinator) -> None:
        """Initialize the Flo switch."""
        super().__init__("shutoff_valve", device)
        self._pending_target: str | None = None
        self._pending_until: datetime | None = None
        self._attr_is_on = self._compute_is_on()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Open the valve."""
        await self._device.api_client.set_valve_state(self._device.id, "open")
        self._start_command_grace("open")
        self._attr_is_on = True
        self.async_write_ha_state()
        await self._device.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close the valve."""
        await self._device.api_client.set_valve_state(self._device.id, "closed")
        self._start_command_grace("closed")
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._device.async_request_refresh()

    def _start_command_grace(self, target: str) -> None:
        """Remember a command we just sent so the next poll can't undo it."""
        self._pending_target = target
        self._pending_until = dt_util.utcnow() + COMMAND_GRACE_PERIOD

    def _compute_is_on(self) -> bool:
        """Return whether the valve should read as open.

        The Moen Flo API exposes two valve fields: ``lastKnown`` (the physical state
        the device last reported) and ``target`` (the state the cloud was last told to
        reach). ``lastKnown`` is the source of truth: it is the only field that moves
        when the device closes the valve on its own, e.g. an automatic shutoff after a
        leak or unusual-activity alert. ``target`` stays at ``open`` through such an
        event, so a switch driven by ``target`` keeps reporting the water as on while
        it is actually shut off.

        The one place ``lastKnown`` misleads is right after a command sent from Home
        Assistant: ``target`` flips immediately but ``lastKnown`` lags by up to a poll
        cycle, so the post-command refresh would briefly snap the switch back. To cover
        that, a command issued here is remembered for :data:`COMMAND_GRACE_PERIOD` and
        wins until the device confirms it or the grace period runs out.
        """
        last_known = self._device.last_known_valve_state

        if self._pending_target is not None:
            confirmed = last_known == self._pending_target
            expired = (
                self._pending_until is None or dt_util.utcnow() >= self._pending_until
            )
            if confirmed or expired:
                self._pending_target = None
                self._pending_until = None
            else:
                return self._pending_target == "open"

        if last_known in ("open", "closed"):
            return last_known == "open"

        # ``inTransition`` or missing: keep the current reading if we have one,
        # otherwise fall back to the commanded state.
        if self._attr_is_on is not None:
            return bool(self._attr_is_on)
        return self._device.target_valve_state == "open"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._compute_is_on()
        super()._handle_coordinator_update()

    async def async_set_mode_home(self):
        """Set the Flo location to home mode."""
        await self._device.async_set_mode_home()

    async def async_set_mode_away(self):
        """Set the Flo location to away mode."""
        await self._device.async_set_mode_away()

    async def async_set_mode_sleep(self, sleep_minutes, revert_to_mode):
        """Set the Flo location to sleep mode."""
        await self._device.async_set_mode_sleep(sleep_minutes, revert_to_mode)

    async def async_run_health_test(self):
        """Run a Flo device health test."""
        await self._device.async_run_health_test()
