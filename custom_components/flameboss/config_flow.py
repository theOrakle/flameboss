from __future__ import annotations

import logging
import aiomqtt
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback

from .api import async_test_connection
from .const import (
    CONF_DEVICE_IDS,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    DEFAULT_MQTT_HOST,
    DEFAULT_MQTT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _parse_device_ids(raw: str) -> list[int]:
    if not raw:
        return []
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part and part.isdigit():
            ids.append(int(part))
    return sorted(set(ids))


class FlameBossConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_MQTT_HOST) or "").strip()
            port = int(user_input.get(CONF_MQTT_PORT) or DEFAULT_MQTT_PORT)

            if not host:
                errors["base"] = "host_required"
                return self.async_show_form(step_id="user", data_schema=self._schema(user_input), errors=errors)

            try:
                await async_test_connection(host, port)
            except (aiomqtt.MqttError, TimeoutError, OSError) as err:
                _LOGGER.debug("Cannot connect to MQTT broker %s:%s: %s", host, port, err)
                errors["base"] = "cannot_connect"
                return self.async_show_form(step_id="user", data_schema=self._schema(user_input), errors=errors)

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            data = {
                CONF_MQTT_HOST: host,
                CONF_MQTT_PORT: port,
                CONF_DEVICE_IDS: _parse_device_ids(user_input.get(CONF_DEVICE_IDS, "")),
            }
            return self.async_create_entry(title=f"Flame Boss ({host})", data=data)

        return self.async_show_form(step_id="user", data_schema=self._schema(), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> FlameBossOptionsFlow:
        """Create the options flow."""
        return FlameBossOptionsFlow(config_entry)

    def _schema(self, user_input: dict | None = None) -> vol.Schema:
        user_input = user_input or {}
        return vol.Schema(
            {
                vol.Required(CONF_MQTT_HOST, default=user_input.get(CONF_MQTT_HOST, DEFAULT_MQTT_HOST)): str,
                vol.Required(CONF_MQTT_PORT, default=user_input.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)): int,
                vol.Optional(CONF_DEVICE_IDS, default=user_input.get(CONF_DEVICE_IDS, "")): str,
            }
        )


class FlameBossOptionsFlow(config_entries.OptionsFlowWithReload):
    """Options flow for Flame Boss: lets the device ID allowlist be edited.

    Subclassing OptionsFlowWithReload (rather than plain OptionsFlow) makes
    HA reload the entry safely via its own state machine after options are
    saved, so a changed device list actually re-subscribes MQTT topics and
    re-seeds entities instead of silently doing nothing until a manual
    restart.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
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
