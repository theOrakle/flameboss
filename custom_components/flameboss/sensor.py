from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback


from .const import SIGNAL_DEVICE_DISCOVERED, DOMAIN, CONF_DEVICE_IDS
from .coordinator import FlameBossCoordinator
from .entity import FlameBossEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    device_ids = entry.options.get(CONF_DEVICE_IDS, entry.data.get(CONF_DEVICE_IDS, []))
    added: set[int] = set()

    def _schedule_add(entities):
        # Ensure entity addition happens in HA event loop even if discovery callback
        # is invoked from another thread.
        hass.loop.call_soon_threadsafe(async_add_entities, entities, True)

    def _add_device(did: int) -> None:
        if did in added:
            return
        added.add(did)
        _schedule_add([
        FlameBossBlowerDuty(coordinator, entry, did),
        FlameBossMeatTemp(coordinator, entry, did, 1),
        FlameBossMeatTemp(coordinator, entry, did, 2),
        FlameBossMeatTemp(coordinator, entry, did, 3),
        FlameBossPitTemperature(coordinator, entry, did),
        FlameBossSetTemperature(coordinator, entry, did),
    ])

    # Seed entities from configured IDs, otherwise from any IDs already observed
    # by the coordinator during startup (wildcard subscription mode).
    seed = list(device_ids) if device_ids else list(getattr(coordinator, "discovered_device_ids", set()))
    for did in seed:
        _add_device(int(did))

    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}", _add_device)
    )



class FlameBossBlowerDuty(FlameBossEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Blower Duty"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FlameBossCoordinator, entry: ConfigEntry, device_id: int) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_blower"

    @property
    def native_value(self) -> float | None:
        dev: dict[str, Any] = (self.coordinator.data or {}).get(str(self._device_id), {})
        val = dev.get("blower")
        if val is None:
            return None
        try:
            return float(val) / 100.0
        except Exception:  # noqa: BLE001
            return None


class FlameBossMeatTemp(FlameBossEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FlameBossCoordinator, entry: ConfigEntry, device_id: int, probe: int) -> None:
        super().__init__(coordinator, entry, device_id)
        self._probe = probe
        self._attr_name = f"Meat {probe} Temperature"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_meat_{probe}"
        if probe in (2, 3):
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> float | None:
        dev: dict[str, Any] = (self.coordinator.data or {}).get(str(self._device_id), {})
        key = f"meat_{self._probe}"
        val = dev.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except Exception:  # noqa: BLE001
            return None


class FlameBossPitTemperature(FlameBossEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Pit Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: FlameBossCoordinator, entry: ConfigEntry, device_id: int) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_pit"

    @property
    def native_value(self) -> float | None:
        dev: dict[str, Any] = (self.coordinator.data or {}).get(str(self._device_id), {})
        val = dev.get("pit_temp")
        if val is None:
            return None
        try:
            return float(val)
        except Exception:  # noqa: BLE001
            return None


class FlameBossSetTemperature(FlameBossEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Set Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: FlameBossCoordinator, entry: ConfigEntry, device_id: int) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_set_temp"

    @property
    def native_value(self) -> float | None:
        dev: dict[str, Any] = (self.coordinator.data or {}).get(str(self._device_id), {})
        val = dev.get("set_temp_f")
        if val is None:
            return None
        try:
            return float(val)
        except Exception:  # noqa: BLE001
            return None


def _build_entities(coordinator, device_id: int):
    return [
        FlameBossBlowerDuty(coordinator, device_id),
        FlameBossMeatTemp(coordinator, device_id, 1),
        FlameBossMeatTemp(coordinator, device_id, 2),
        FlameBossMeatTemp(coordinator, device_id, 3),
        FlameBossPitTemp(coordinator, device_id),
        FlameBossSetTemp(coordinator, device_id),
        FlameBossOnlineBinarySensor(coordinator, device_id),
    ]
