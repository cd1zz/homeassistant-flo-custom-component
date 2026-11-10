"""Tests for how the shutoff valve switch decides whether the water is on."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.flo.switch import COMMAND_GRACE_PERIOD, FloSwitch


def make_switch(last_known, target="open"):
    device = MagicMock()
    device.mac_address = "aa:bb:cc:dd:ee:ff"
    device.id = "device-1"
    device.last_known_valve_state = last_known
    device.target_valve_state = target
    return FloSwitch(device), device


def poll(switch):
    """Recompute state the way a coordinator update does."""
    switch._attr_is_on = switch._compute_is_on()
    return switch._attr_is_on


def test_open_valve_reads_on():
    switch, _ = make_switch("open")
    assert switch.is_on is True


def test_automatic_shutoff_reads_off_even_though_target_is_open():
    # A device-initiated closure only moves lastKnown; target stays "open".
    switch, device = make_switch("open", target="open")
    device.last_known_valve_state = "closed"
    assert poll(switch) is False


def test_command_wins_until_device_confirms():
    switch, device = make_switch("open")
    switch._start_command_grace("closed")
    # Device has not reported the move yet.
    assert poll(switch) is False
    device.last_known_valve_state = "closed"
    assert poll(switch) is False
    assert switch._pending_target is None


def test_open_command_wins_during_grace():
    switch, device = make_switch("closed", target="closed")
    switch._start_command_grace("open")
    assert poll(switch) is True


def test_unconfirmed_command_expires_to_reported_state():
    switch, device = make_switch("open")
    switch._start_command_grace("closed")
    later = dt_util.utcnow() + COMMAND_GRACE_PERIOD + timedelta(seconds=1)
    with patch("custom_components.flo.switch.dt_util.utcnow", return_value=later):
        assert poll(switch) is True
    assert switch._pending_target is None


def test_device_closure_after_confirmed_open_is_not_masked():
    switch, device = make_switch("closed", target="closed")
    switch._start_command_grace("open")
    device.last_known_valve_state = "open"
    assert poll(switch) is True
    device.last_known_valve_state = "closed"
    assert poll(switch) is False


@pytest.mark.parametrize("previous", [True, False])
def test_in_transition_keeps_previous_reading(previous):
    switch, device = make_switch("open" if previous else "closed")
    device.last_known_valve_state = "inTransition"
    assert poll(switch) is previous


def test_unknown_state_at_startup_falls_back_to_target():
    device = MagicMock()
    device.mac_address = None
    device.id = "device-1"
    device.last_known_valve_state = None
    device.target_valve_state = "closed"
    assert FloSwitch(device).is_on is False
