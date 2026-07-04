from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FlameBossCoordinator
from .const import DOMAIN

class FlameBossEntity(CoordinatorEntity[FlameBossCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: FlameBossCoordinator, entry: ConfigEntry, device_id: int) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id

    @property
    def device_info(self) -> DeviceInfo:
        dev = (self.coordinator.data or {}).get(str(self._device_id), {})
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device_id))},
            name=f"Flame Boss {self._device_id}",
            manufacturer="Flame Boss",
            model="Temperature Controller",
            sw_version=str(v) if (v := dev.get("app_version")) is not None else None,
            hw_version=str(v) if (v := dev.get("hw_id")) is not None else None,
        )
