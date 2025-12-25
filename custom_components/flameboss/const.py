from __future__ import annotations

import logging
LOGGER = logging.getLogger(__name__)


DOMAIN = "flameboss"

DEFAULT_MQTT_HOST = ""
DEFAULT_MQTT_PORT = 1883


# Platforms we provide entities for
PLATFORMS: list[str] = ["sensor", "climate", "binary_sensor"]

# Config keys
CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_USE_TLS = "use_tls"
CONF_VALIDATE_CERT = "validate_cert"
CONF_DEVICE_IDS = "device_ids"

DEFAULT_HOST = "flameboss.local"
DEFAULT_PORT_TLS = 8883
DEFAULT_PORT_PLAINTEXT = 1883

# Topics (Flame Boss publishes under flameboss/<device_id>/send/*)
TOPIC_SEND_WILDCARD = "flameboss/{device_id}/send/#"
TOPIC_SEND_DATA = "flameboss/{device_id}/send/data"
TOPIC_SEND_OPEN = "flameboss/{device_id}/send/open"

# Commands to controller
TOPIC_RECV = "flameboss/{device_id}/recv"

SIGNAL_DEVICE_DISCOVERED = "flameboss_device_discovered"

OFFLINE_AFTER_SECONDS = 15


TOPIC_SEND_FW = "flameboss/{device_id}/send/fw"
