from __future__ import annotations

import asyncio
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_IDS,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    DEFAULT_MQTT_HOST,
    DEFAULT_MQTT_PORT,
    DOMAIN,
)

_MQTT_ZC_TYPE = "_mqtt._tcp.local."


def _parse_device_ids(raw: str) -> list[int]:
    if not raw:
        return []
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part and part.isdigit():
            ids.append(int(part))
    return sorted(set(ids))


async def _discover_mqtt_brokers(hass: HomeAssistant) -> list[tuple[str, int]]:
    """Try to discover MQTT brokers via zeroconf (_mqtt._tcp.local.)."""
    try:
        from homeassistant.components import zeroconf as zc

        zeroconf = await zc.async_get_instance(hass)
        browser = zc.ZeroconfServiceBrowser(zeroconf, _MQTT_ZC_TYPE)
        await asyncio.sleep(1.0)
        results: list[tuple[str, int]] = []
        for info in browser.discovered:
            if info.host and info.port:
                results.append((info.host.rstrip("."), int(info.port)))
        browser.async_cancel()

        seen: set[tuple[str, int]] = set()
        out: list[tuple[str, int]] = []
        for hp in results:
            if hp not in seen:
                seen.add(hp)
                out.append(hp)
        return out
    except Exception:
        return []


class FlameBossConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_MQTT_HOST) or "").strip()
            port = int(user_input.get(CONF_MQTT_PORT) or DEFAULT_MQTT_PORT)

            if not host:
                found = await _discover_mqtt_brokers(self.hass)
                if len(found) == 1:
                    host, port = found[0]
                else:
                    errors["base"] = "host_required"
                    return self.async_show_form(step_id="user", data_schema=self._schema(), errors=errors)

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            data = {
                CONF_MQTT_HOST: host,
                CONF_MQTT_PORT: port,
                CONF_DEVICE_IDS: _parse_device_ids(user_input.get(CONF_DEVICE_IDS, "")),
            }
            return self.async_create_entry(title=f"Flame Boss ({host})", data=data)

        return self.async_show_form(step_id="user", data_schema=self._schema(), errors=errors)

    def _schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_MQTT_HOST, default=DEFAULT_MQTT_HOST): str,
                vol.Required(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): int,
                vol.Optional(CONF_DEVICE_IDS, default=""): str,
            }
        )


class FlameBossOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            options = dict(self._config_entry.options)
            options[CONF_DEVICE_IDS] = _parse_device_ids(user_input.get(CONF_DEVICE_IDS, ""))
            return self.async_create_entry(title="", data=options)

        existing_ids = self._config_entry.options.get(CONF_DEVICE_IDS)
        if existing_ids is None:
            existing_ids = self._config_entry.data.get(CONF_DEVICE_IDS, [])
        default_ids = ",".join(str(i) for i in existing_ids)


        schema = vol.Schema(
            {
                vol.Optional(CONF_DEVICE_IDS, default=default_ids): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> FlameBossOptionsFlow:
    return FlameBossOptionsFlow(config_entry)
