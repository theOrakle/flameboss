"""Flame Boss integration."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import FlameBossConfigEntry, FlameBossCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: FlameBossConfigEntry) -> bool:
    """Set up Flame Boss from a config entry.

    The MQTT broker (or the controllers behind it) may be offline when Home
    Assistant starts and come and go afterwards, so setup never waits for it:
    the client keeps reconnecting in the background and entities fill in as
    soon as messages arrive.
    """
    coordinator = FlameBossCoordinator(hass, entry)
    await coordinator.async_start()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FlameBossConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
