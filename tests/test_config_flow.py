"""Tests for the Flame Boss config and options flows."""
from __future__ import annotations

from unittest.mock import MagicMock

import aiomqtt
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flameboss.const import (
    CONF_DEVICE_IDS,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    DOMAIN,
)

USER_INPUT = {CONF_MQTT_HOST: " broker.local ", CONF_MQTT_PORT: 1883, CONF_DEVICE_IDS: "1234, 99, x"}


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_broker: MagicMock) -> None:
    """A reachable broker creates an entry keyed by host:port."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Flame Boss (broker.local)"
    assert result["data"] == {
        CONF_MQTT_HOST: "broker.local",
        CONF_MQTT_PORT: 1883,
        CONF_DEVICE_IDS: [99, 1234],
    }
    assert result["result"].unique_id == "broker.local:1883"
    mock_broker.assert_any_await("broker.local", 1883)


async def test_user_flow_connection_error_recovers(
    hass: HomeAssistant, mock_broker: MagicMock
) -> None:
    """An unreachable broker shows an error, keeps the typed values, and can be retried."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    mock_broker.side_effect = aiomqtt.MqttError("refused")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_broker.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_timeout_is_a_connection_error(
    hass: HomeAssistant, mock_broker: MagicMock
) -> None:
    """A broker that never answers is reported as unreachable."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    mock_broker.side_effect = TimeoutError
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant, mock_broker: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The same broker cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MQTT_HOST: "broker.local", CONF_MQTT_PORT: 1883}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_blank_host_is_rejected(
    hass: HomeAssistant, mock_broker: MagicMock
) -> None:
    """A blank host is refused before any connection is attempted."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MQTT_HOST: " ", CONF_MQTT_PORT: 1883}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "host_required"}
    mock_broker.assert_not_awaited()


async def test_options_flow_saves_device_ids(
    hass: HomeAssistant, mock_broker: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The controller allow-list can be edited after setup."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEVICE_IDS: "1234, 5678"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert mock_config_entry.options[CONF_DEVICE_IDS] == [1234, 5678]


async def test_user_flow_without_device_ids_uses_autodiscovery(
    hass: HomeAssistant, mock_broker: MagicMock
) -> None:
    """Leaving the controller IDs blank stores an empty list (auto-discovery)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MQTT_HOST: "broker.local", CONF_MQTT_PORT: 1883}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_IDS] == []
