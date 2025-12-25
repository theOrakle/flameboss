from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import UnitOfTemperature

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
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
        _schedule_add([FlameBossPitController(coordinator, entry, did)])

    seed = list(device_ids) if device_ids else list(getattr(coordinator, "discovered_device_ids", set()))
    for did in seed:
        _add_device(int(did))

    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}", _add_device)
    )



class FlameBossPitController(FlameBossEntity, ClimateEntity):
    @property
    def target_temperature_step(self):
        return 5.0

    @property
    def max_temp(self):
        return 450.0

    @property
    def min_temp(self):
        return 100.0

    @property
    def temperature_unit(self):
        return UnitOfTemperature.FAHRENHEIT

    _attr_has_entity_name = True
    _attr_name = "Pit Controller"
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_target_temperature_step = 1.0
    _attr_min_temp = 100.0
    _attr_max_temp = 450.0

    def __init__(self, coordinator: FlameBossCoordinator, entry: ConfigEntry, device_id: int) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_pit_climate"

    @property
    def available(self) -> bool:
        return super().available


    @property
    def hvac_mode(self):
        """Return current HVAC mode."""
        # Pit controller behaves like a heater: HEAT when online, OFF when offline
        return HVACMode.HEAT if self.available else HVACMode.OFF
    @property
    def current_temperature(self):
        dev = (self.coordinator.data or {}).get(str(self._device_id), {})
        return dev.get("pit_temp")

    @property
    def target_temperature(self):
        dev = (self.coordinator.data or {}).get(str(self._device_id), {})
        return dev.get("set_temp_f")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if not self.available:
            _LOGGER.debug("Controller %s offline; refusing to set temperature", self._device_id)
            return
        temp = kwargs.get("temperature")
        if temp is None:
            return

        t = float(temp)
        if t < self._attr_min_temp:
            t = self._attr_min_temp
        elif t > self._attr_max_temp:
            t = self._attr_max_temp

        await self.coordinator.async_set_pit_setpoint_f(self._device_id, t)
