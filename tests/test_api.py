"""Tests for the Flame Boss MQTT client's reconnect behaviour."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import aiomqtt

from custom_components.flameboss.api import FlameBossMqttClient, FlameBossMqttConfig


async def test_unreachable_broker_is_retried_and_logged_once(caplog) -> None:
    """An offline broker is retried forever, with a single warning rather than a log storm."""
    client = FlameBossMqttClient(
        FlameBossMqttConfig(host="broker.local", port=1883), MagicMock()
    )
    attempts = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 3:
            client._stop_event.set()

    errors = [OSError(113, "Host is unreachable"), aiomqtt.MqttError("refused"), OSError(113, "x")]
    with (
        patch("custom_components.flameboss.api.aiomqtt.Client", side_effect=errors),
        patch("custom_components.flameboss.api.asyncio.sleep", new=fake_sleep),
        caplog.at_level(logging.DEBUG, logger="custom_components.flameboss.api"),
    ):
        await client._run()

    assert attempts == 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "broker.local:1883 is unavailable" in warnings[0].getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_stop_cancels_the_background_task() -> None:
    """Stopping the client cancels its connection loop cleanly."""
    client = FlameBossMqttClient(
        FlameBossMqttConfig(host="broker.local", port=1883), MagicMock()
    )
    with patch(
        "custom_components.flameboss.api.aiomqtt.Client", side_effect=OSError("down")
    ):
        await client.start()
        await asyncio.sleep(0)  # let the loop hit its first failure and start its 5s wait
        await client.stop()
    assert client._task is None
