"""Tests for Flame Boss setup, unload and entities."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import aiomqtt
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.flameboss.const import DOMAIN

from .conftest import DEVICE_ID, TEMPS_PAYLOAD


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, mock_broker: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The entry loads, seeds entities for the configured controller, and unloads."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    mock_broker.client.start.assert_awaited_once()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, str(DEVICE_ID)), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Flame Boss"

    assert hass.states.get("climate.flame_boss_1234_pit_controller") is not None
    assert hass.states.get("sensor.flame_boss_1234_blower_duty") is not None
    assert hass.states.get("binary_sensor.flame_boss_1234_online") is not None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_broker.client.stop.assert_awaited_once()


async def test_mqtt_message_updates_entities(
    hass: HomeAssistant, mock_broker: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A temps message flows through to the climate entity and sensors."""
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data

    coordinator._on_mqtt_message(DEVICE_ID, TEMPS_PAYLOAD, "flameboss/1234/send/data")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()

    climate = hass.states.get("climate.flame_boss_1234_pit_controller")
    assert climate.attributes["current_temperature"] == 230.0
    assert climate.attributes["temperature"] == 230.0
    assert hass.states.get("sensor.flame_boss_1234_meat_1_temperature").state == "140.0"
    assert hass.states.get("sensor.flame_boss_1234_blower_duty").state == "50.0"
    assert hass.states.get("binary_sensor.flame_boss_1234_online").state == "on"


async def test_set_temperature_publishes_to_controller(
    hass: HomeAssistant, mock_broker: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Setting the climate target publishes a tenths-of-°C command."""
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    coordinator._on_mqtt_message(DEVICE_ID, TEMPS_PAYLOAD, "flameboss/1234/send/data")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.flame_boss_1234_pit_controller", "temperature": 250},
        blocking=True,
    )
    # 250 °F = 121.1 °C -> 1211 tenths
    mock_broker.client.async_publish_set_temp_tenth_c.assert_awaited_once_with(DEVICE_ID, 1211)


async def test_autodiscovery_adds_new_controller(
    hass: HomeAssistant, mock_broker: MagicMock
) -> None:
    """With no configured IDs, a controller seen on the broker gets entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="broker.local:1883",
        data={"mqtt_host": "broker.local", "mqtt_port": 1883, "device_ids": []},
    )
    await _setup(hass, entry)
    assert hass.states.get("binary_sensor.flame_boss_555_online") is None

    entry.runtime_data._on_mqtt_message(555, TEMPS_PAYLOAD, "flameboss/555/send/data")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.flame_boss_555_online") is not None


async def test_setup_does_not_wait_for_the_broker(
    hass: HomeAssistant, mock_broker: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """An offline broker at startup must not fail setup; the client reconnects itself."""
    mock_broker.side_effect = aiomqtt.MqttError("refused")
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    mock_broker.client.start.assert_awaited_once()
    mock_broker.assert_not_awaited()
    # Entities exist for the configured controller and simply have no values yet.
    assert hass.states.get("binary_sensor.flame_boss_1234_online").state == "off"
