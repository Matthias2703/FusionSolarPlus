"""Number platform for FusionSolar Plus."""

import logging
from typing import Dict, Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .devices.charger.number import ChargerNumberHandler
from .device_handler import BaseDeviceHandler

_LOGGER = logging.getLogger(__name__)


class NumberHandlerFactory:
    """Create appropriate number handlers."""

    @staticmethod
    def create_handler(
        hass: HomeAssistant, entry: ConfigEntry, device_info: Dict[str, Any]
    ) -> BaseDeviceHandler:
        if entry.data.get("device_type") == "Charger":
            return ChargerNumberHandler(hass, entry, device_info)
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up select platform."""
    device_name = entry.data.get("device_name")
    device_info = hass.data[DOMAIN].get(f"{entry.entry_id}_device_info")

    if not device_info:
        _LOGGER.debug(
            "Device info not found for device %s. Skipping number setup.", device_name
        )
        return

    try:
        handler = NumberHandlerFactory.create_handler(hass, entry, device_info)
        if handler is None:
            return

        coordinator = hass.data[DOMAIN].get(f"{entry.entry_id}_coordinator")
        if coordinator is None:
            return

        entities = handler.create_entities(coordinator)
        _LOGGER.info(
            "Adding %d number entities for device %s", len(entities), device_name
        )
        async_add_entities(entities)

    except Exception as e:
        _LOGGER.error("Failed to set up numbers for device %s: %s", device_name, e)
