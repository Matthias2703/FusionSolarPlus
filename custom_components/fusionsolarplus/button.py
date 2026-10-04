"""Button platform for FusionSolar Plus."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHARGER_CONTROL, DEFAULT_CHARGER_CONTROL, DOMAIN
from .devices.charger.button import ChargerButtonHandler

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up button platform (charger start/stop, only with charger control on)."""
    if entry.data.get("device_type") != "Charger" or not entry.options.get(
        CONF_CHARGER_CONTROL, DEFAULT_CHARGER_CONTROL
    ):
        return

    device_name = entry.data.get("device_name")
    device_info = hass.data[DOMAIN].get(f"{entry.entry_id}_device_info")
    coordinator = hass.data[DOMAIN].get(f"{entry.entry_id}_coordinator")
    if not device_info or coordinator is None:
        return

    try:
        entities = ChargerButtonHandler(hass, entry, device_info).create_entities(
            coordinator
        )
        _LOGGER.info(
            "Adding %d button entities for device %s", len(entities), device_name
        )
        async_add_entities(entities)
    except Exception as e:
        _LOGGER.error("Failed to set up buttons for device %s: %s", device_name, e)
