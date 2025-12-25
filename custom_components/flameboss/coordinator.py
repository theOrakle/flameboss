from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import FlameBossMqttClient, FlameBossMqttConfig
from .const import DOMAIN, LOGGER, SIGNAL_DEVICE_DISCOVERED


def _device_discovered_signal(entry_id: str) -> str:
    """Return an entry-scoped dispatcher signal for new device discovery."""
    return f"{SIGNAL_DEVICE_DISCOVERED}_{entry_id}"

def _tenth_c_to_f(val: int | float | None) -> float | None:
    """Convert tenths °C to °F."""
    if val is None:
        return None
    # -32767 is Flame Boss "not present" sentinel
    try:
        if int(val) == -32767:
            return None
        c = float(val) / 10.0
        return (c * 9.0 / 5.0) + 32.0
    except Exception:
        return None


def _f_to_tenth_c(f: float) -> int:
    """Convert °F to tenths °C (rounded)."""
    c = (float(f) - 32.0) * 5.0 / 9.0
    return int(round(c * 10.0))


@dataclass(frozen=True)
class DeviceState:
    last_msg_monotonic: float
    last_seen: float


class FlameBossCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    _last_debug_refresh: float = 0.0  # fallback default
    """Coordinator for Flame Boss local MQTT (push-based)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._last_debug_refresh = 0.0
        self.hass = hass
        self.entry = entry

        # DataUpdateCoordinator uses .data; initialize to {} not None
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=None,  # push-only
            update_method=self._async_update_data,
        )

        self.data: dict[str, Any] = {}

        self._cfg = FlameBossMqttConfig.from_entry(entry)
        self._client = FlameBossMqttClient(self._cfg, self._on_mqtt_message)

        self._lock = asyncio.Lock()
        self._pending_refresh = False

        self._last_message_monotonic: dict[int, float] = {}
        self._offline_unsub = None

        # Autodiscovery: device IDs we've seen on the broker.
        self._discovered_device_ids: set[int] = set()

        # rate limit for setpoint publishes per device
        self._last_publish_monotonic: dict[int, float] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        # No polling; return current snapshot
        return self.data

    async def async_start(self) -> None:
        await self._client.start()
        # Offline detection: every 5s, mark offline if no message for 15s
        self._offline_unsub = async_track_time_interval(
            self.hass, self._offline_check, timedelta(seconds=5)
        )

    async def async_stop(self) -> None:
        if self._offline_unsub is not None:
            self._offline_unsub()
            self._offline_unsub = None
        await self._client.stop()

    async def _offline_check(self, _now) -> None:
        now = time.monotonic()
        changed = False
        async with self._lock:
            for did, last in list(self._last_message_monotonic.items()):
                dev = dict((self.data or {}).get(str(did), {}))
                # 3 x 5s retries == 15s
                is_online = (now - last) <= 15.0
                if dev.get("online") != is_online:
                    dev["online"] = is_online
                    all_data = dict(self.data or {})
                    all_data[str(did)] = dev
                    self.data = all_data
                    changed = True
        if changed:
            self._schedule_refresh()

    @callback
    def _schedule_refresh(self) -> None:
        if self._pending_refresh:
            return
        self._pending_refresh = True

        @callback
        def _do(_now) -> None:
            self._pending_refresh = False
            # This is safe on the event loop
            self.async_set_updated_data(self.data)
            now = time.monotonic()
            if now - self._last_debug_refresh > 30:
                self._last_debug_refresh = now
                LOGGER.debug("Flame Boss: state refresh pushed")

        async_call_later(self.hass, 1.0, _do)

    @callback
    def _on_mqtt_message(self, device_id: int, payload: dict[str, Any], topic: str) -> None:
        """Handle incoming MQTT message (called from the HA event loop)."""
        # Track last message time for offline detection
        self._last_message_monotonic[device_id] = time.monotonic()

        # Autodiscovery: first time we see a device_id, notify platforms so they can
        # add entities dynamically.
        if device_id not in self._discovered_device_ids:
            self._discovered_device_ids.add(device_id)
            self.hass.loop.call_soon_threadsafe(async_dispatcher_send, self.hass, _device_discovered_signal(self.entry.entry_id), device_id)

        async def _update() -> None:
            async with self._lock:
                dev = dict((self.data or {}).get(str(device_id), {}))
                name = payload.get("name")

                if name == "temps":
                    temps = payload.get("temps") or []
                    dev["cook_id"] = payload.get("cook_id")
                    dev["sec"] = payload.get("sec")

                    dev["pit_tenth_c"] = temps[0] if len(temps) > 0 else None
                    dev["meat1_tenth_c"] = temps[1] if len(temps) > 1 else None
                    dev["meat2_tenth_c"] = temps[2] if len(temps) > 2 else None
                    dev["meat3_tenth_c"] = temps[3] if len(temps) > 3 else None

                    dev["set_temp"] = payload.get("set_temp")
                    dev["blower"] = payload.get("blower")

                    # Derived Fahrenheit values
                    dev["pit_temp"] = _tenth_c_to_f(dev.get("pit_tenth_c"))
                    dev["meat_1"] = _tenth_c_to_f(dev.get("meat1_tenth_c"))
                    dev["meat_2"] = _tenth_c_to_f(dev.get("meat2_tenth_c"))
                    dev["meat_3"] = _tenth_c_to_f(dev.get("meat3_tenth_c"))
                    dev["set_temp_f"] = _tenth_c_to_f(dev.get("set_temp"))

                    # blower is 0..10000 => percent
                    try:
                        b = float(dev.get("blower") or 0.0)
                        dev["blower_pct"] = max(0.0, min(100.0, b / 100.0))
                    except Exception:
                        dev["blower_pct"] = None

                    dev["online"] = True

                elif name == "versions":
                    dev["hw_id"] = payload.get("hw_id")
                    dev["app"] = payload.get("app")
                    dev["online"] = True

                all_data = dict(self.data or {})
                all_data[str(device_id)] = dev
                self.data = all_data

            self._schedule_refresh()

        self.hass.async_create_task(_update())

    @property
    def discovered_device_ids(self) -> set[int]:
        """Return device IDs observed on the broker (wildcard subscription mode)."""
        return set(self._discovered_device_ids)

    async def async_set_pit_setpoint_f(self, device_id: int, setpoint_f: float) -> None:
        """Publish pit setpoint (°F) to controller via MQTT, with rate limiting."""
        now = time.monotonic()
        last = self._last_publish_monotonic.get(int(device_id), 0.0)
        if now - last < 2.0:
            LOGGER.debug("Rate limiting setpoint publish for %s", device_id)
            return
        self._last_publish_monotonic[int(device_id)] = now

        tenth_c = _f_to_tenth_c(setpoint_f)
        await self._client.async_publish_set_temp_tenth_c(int(device_id), tenth_c)

    def is_device_online(self, device_id: str | int) -> bool:
        """Return True if we've seen recent MQTT data for the device."""
        did = str(device_id)
        dev = (self.data or {}).get(did, {})
        return bool(dev.get("online", False))
