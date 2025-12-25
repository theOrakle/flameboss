from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
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
        _schedule_add([FlameBossOnline(coordinator, entry, did)])

    seed = list(device_ids) if device_ids else list(getattr(coordinator, "discovered_device_ids", set()))
    for did in seed:
        _add_device(int(did))

    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}", _add_device)
    )



class FlameBossOnline(FlameBossEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = "connectivity"

    def __init__(self, coordinator: FlameBossCoordinator, entry: ConfigEntry, device_id: int) -> None:
        super().__init__(coordinator, entry, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_online"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.is_device_online(self._device_id)
