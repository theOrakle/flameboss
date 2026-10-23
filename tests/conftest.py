"""Shared fixtures for the Flame Boss tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flameboss.const import (
    CONF_DEVICE_IDS,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"

DEVICE_ID = 1234

TEMPS_PAYLOAD = {
    "name": "temps",
    "cook_id": 7,
    "sec": 100,
    # pit, meat1, meat2, meat3 in tenths of a degree C
    "temps": [1100, 600, -32767, -32767],
    "set_temp": 1100,
    "blower": 5000,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load the custom integration under test."""


@pytest.fixture(autouse=True)
async def us_units_and_cleanup(hass: HomeAssistant):
    """Report in °F like the controller, and stop the offline timer after each test."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    yield
    await hass.async_block_till_done()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a Flame Boss config entry for one known controller."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Flame Boss (broker.local)",
        unique_id="broker.local:1883",
        data={
            CONF_MQTT_HOST: "broker.local",
            CONF_MQTT_PORT: 1883,
            CONF_DEVICE_IDS: [DEVICE_ID],
        },
    )


@pytest.fixture
def mock_broker() -> Generator[MagicMock]:
    """Patch every MQTT connection: the config-flow test and the long-lived client."""
    with (
        patch(
            "custom_components.flameboss.config_flow.async_test_connection",
            new_callable=AsyncMock,
        ) as setup_test,
        patch("custom_components.flameboss.coordinator.FlameBossMqttClient") as client_cls,
    ):
        client = client_cls.return_value
        client.start = AsyncMock()
        client.stop = AsyncMock()
        client.async_publish_set_temp_tenth_c = AsyncMock()
        setup_test.client = client
        yield setup_test
