import logging
from typing import Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import OpenBankingDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up the Open Banking integration.

    This method initializes the integration by creating and storing the data coordinator,
    ensuring platform setups are forwarded, and triggering the first data refresh.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The configuration entry containing user-defined settings.

    Returns:
        bool: True if the integration is successfully set up.
    """
    hass.data.setdefault(DOMAIN, {})

    # Initialize coordinator
    coordinator: OpenBankingDataUpdateCoordinator = OpenBankingDataUpdateCoordinator(
        hass, entry
    )
    await coordinator.async_initialize(hass)

    # Store coordinator in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator
    }

    _LOGGER.warning("Setting up Nordigen integration...")
    
    # FIRST, decide whether to refresh the coordinator
    # This follows the Home Assistant pattern of getting data before creating entities
    if coordinator._needs_immediate_refresh:
        _LOGGER.warning("Triggering initial refresh to get account data")
        await coordinator.async_config_entry_first_refresh()
    else:
        _LOGGER.warning("Skipping immediate refresh as we're within update interval")
        _LOGGER.warning("Using stored data from previous refresh")
    
    # AFTER deciding on refresh, forward to the sensor platform to create entities
    # By this point, coordinator.data may be populated with fresh or stored data
    _LOGGER.warning("Setting up Nordigen sensors...")
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    _LOGGER.warning("Nordigen Account integration successfully set up.")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload the Open Banking integration.

    Removes the integration’s platforms and cleans up resources when the config entry is removed.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The configuration entry being unloaded.

    Returns:
        bool: True if the integration is successfully unloaded.
    """
    return await hass.config_entries.async_unload_platforms(entry, ["sensor"])
