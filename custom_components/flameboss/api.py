from __future__ import annotations

import asyncio
import json

from homeassistant.config_entries import ConfigEntry
import logging
import ssl
from dataclasses import dataclass
from typing import Any, Callable

import aiomqtt

from .const import (
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_HOST,
    CONF_DEVICE_IDS,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USERNAME,
    CONF_MQTT_PORT,
    CONF_MQTT_HOST,
    DEFAULT_HOST,
    DEFAULT_PORT_TLS,
    DEFAULT_PORT_PLAINTEXT,
    TOPIC_SEND_DATA, TOPIC_SEND_FW,
    TOPIC_SEND_WILDCARD,
    TOPIC_SEND_OPEN,
    TOPIC_RECV,
)

_LOGGER = logging.getLogger(__name__)

# DEBUG_RX_LOG: raw RX logging (topic + payload), rate limited per device/topic
_RX_LOG_MAXLEN = 800
_RX_LOG_MIN_INTERVAL = 1.0  # seconds per (device_id, topic) key


@dataclass
class FlameBossMqttConfig:
    host: str
    port: int
    username: str = ""
    password: str = ""
    use_tls: bool = False
    validate_cert: bool = True
    device_ids: list[int] | None = None

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> "FlameBossMqttConfig":
        """Build config from config entry (data + options). Options win."""
        merged = {**(entry.data or {}), **(entry.options or {})}
        host = str(merged.get(CONF_MQTT_HOST, DEFAULT_MQTT_HOST) or "")
        port = int(merged.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT) or DEFAULT_MQTT_PORT)
        username = str(merged.get(CONF_MQTT_USERNAME, "") or "")
        password = str(merged.get(CONF_MQTT_PASSWORD, "") or "")
        # Device IDs are stored as list[int] in data/options, but older flows may store CSV string.
        raw_ids = merged.get(CONF_DEVICE_IDS)
        device_ids: list[int] | None
        if raw_ids in (None, "", []):
            device_ids = None
        elif isinstance(raw_ids, str):
            device_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
        else:
            device_ids = [int(x) for x in raw_ids]

        return cls(host=host, port=port, username=username, password=password, device_ids=device_ids)


class FlameBossMqttClient:
    """MQTT client for Flame Boss cloud using aiomqtt."""

    def __init__(
        self,
        config: FlameBossMqttConfig,
        on_message: Callable[[int, dict[str, Any], str], None],
    ) -> None:
        self._cfg = config
        self._on_message = on_message
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._tls_context: ssl.SSLContext | None = None

        # per (device_id, topic) monotonic timestamps to rate limit debug RX logging
        self._rx_log_last: dict[tuple[str, str], float] = {}

    async def start(self) -> None:
        self._stop_event.clear()
        if self._cfg.use_tls and self._tls_context is None:
            # Avoid HA asyncio blocking warnings.
            if self._cfg.validate_cert:
                self._tls_context = await asyncio.to_thread(ssl.create_default_context)
            else:
                self._tls_context = await asyncio.to_thread(ssl._create_unverified_context)
        self._task = asyncio.create_task(self._run(), name="flameboss_mqtt")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        port = self._cfg.port or (DEFAULT_PORT_TLS if self._cfg.use_tls else DEFAULT_PORT_PLAINTEXT)
        username = self._cfg.username or None
        password = self._cfg.password or None

        while not self._stop_event.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self._cfg.host,
                    port=port,
                    username=username,
                    password=password,
                    tls_context=self._tls_context if self._cfg.use_tls else None,
                    keepalive=60,
                ) as client:
                    if self._cfg.device_ids:
                        topics: list[str] = []
                        for did in self._cfg.device_ids:
                            topics.extend(
                                [
                                    TOPIC_SEND_DATA.format(device_id=did),
                                    TOPIC_SEND_FW.format(device_id=did),
                                ]
                            )
                    else:
                        # Broad subscription for autodiscovery.
                        topics = ["flameboss/#"]

                    for t in topics:
                        await client.subscribe(t)

                    _LOGGER.info("Connected to Flame Boss MQTT and subscribed to %s", topics)
                    _LOGGER.debug("Subscription mode: %s", "wildcard" if any(("#" in t) or ("+" in t) for t in topics) else "device-specific")

                    async for message in client.messages:
                        if self._stop_event.is_set():
                            break
                        try:
                            topic = str(message.topic)
                            payload_txt = message.payload.decode("utf-8", errors="ignore")
                            data = json.loads(payload_txt)

                            parts = topic.split("/")
                            if len(parts) < 4 or not parts[1].isdigit():
                                continue
                            device_id = int(parts[1])

                            if isinstance(data, dict):
                                # DEBUG_RX_LOG (topic + payload), rate limited per (device_id, topic)
                                if _LOGGER.isEnabledFor(logging.DEBUG):
                                    try:
                                        import time as _t

                                        _now = _t.monotonic()
                                        _key = (str(device_id), str(topic))
                                        _last = self._rx_log_last.get(_key, 0.0)
                                        if _now - _last >= _RX_LOG_MIN_INTERVAL:
                                            self._rx_log_last[_key] = _now
                                            _p = payload_txt
                                            if len(_p) > _RX_LOG_MAXLEN:
                                                _p = _p[:_RX_LOG_MAXLEN] + "…"
                                            _LOGGER.debug(
                                                "MQTT RX topic=%s device_id=%s payload=%s",
                                                topic,
                                                device_id,
                                                _p,
                                            )
                                    except Exception:  # pragma: no cover
                                        _LOGGER.debug(
                                            "MQTT RX topic=%s device_id=%s (payload log failed)",
                                            topic,
                                            device_id,
                                        )

                                self._on_message(device_id, data, topic)
                        except Exception as err:  # noqa: BLE001
                            _LOGGER.debug("Bad message from Flame Boss: %s", err, exc_info=True)

            except aiomqtt.MqttError as err:
                _LOGGER.debug("Flame Boss MQTT error: %s. Reconnecting in 5s", err)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Unexpected Flame Boss MQTT failure: %s", err)
                await asyncio.sleep(5)

    async def async_publish_set_temp_tenth_c(self, device_id: int, value_tenth_c: int) -> None:
        """Publish set_temp command using tenths of °C."""
        port = self._cfg.port or (DEFAULT_PORT_TLS if self._cfg.use_tls else DEFAULT_PORT_PLAINTEXT)
        username = self._cfg.username or None
        password = self._cfg.password or None
        topic = TOPIC_RECV.format(device_id=device_id)
        payload = json.dumps({"name": "set_temp", "value": int(value_tenth_c)})

        async with aiomqtt.Client(
            hostname=self._cfg.host,
            port=port,
            username=username,
            password=password,
            tls_context=self._tls_context if self._cfg.use_tls else None,
                    keepalive=60,
        ) as client:
            await client.publish(topic, payload, qos=0)


    async def set_pit_setpoint(self, device_id: int, setpoint_tenth_c: int) -> None:
        """Publish a new pit setpoint to the controller."""
        # Publish as JSON to the recv topic (local broker forwards to controller)
        payload = json.dumps({"name": "set_temp", "set_temp": int(setpoint_tenth_c)})
        # Connect just for publish to keep things simple
        tls_context = self._tls_context if self._cfg.use_tls else None
        username = self._cfg.username or None
        password = self._cfg.password or None
        async with aiomqtt.Client(
            hostname=self._cfg.host,
            port=self._cfg.port,
            username=username,
            password=password,
            tls_context=tls_context,
        ) as client:
            await client.publish(TOPIC_RECV.format(device_id=device_id), payload)
