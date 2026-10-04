"""Button platform for Charger devices: start and stop a charge."""

import logging
from typing import Any, Dict, List

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ...const import DOMAIN
from ...device_handler import BaseDeviceHandler

_LOGGER = logging.getLogger(__name__)


class ChargerButtonHandler(BaseDeviceHandler):
    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        args = (
            coordinator,
            self.hass,
            self.entry.entry_id,
            self.device_info,
            self.device_id,
        )
        return [
            FusionSolarChargeButton(*args, "start_charging", "mdi:play-circle"),
            FusionSolarChargeButton(*args, "stop_charging", "mdi:stop-circle"),
        ]


class FusionSolarChargeButton(CoordinatorEntity, ButtonEntity):
    """Sends the app's start-charge / stop-charge request.

    The cloud answers with the new charge status; the sensors pick the change
    up on the next poll, which is requested right after the command.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        hass: HomeAssistant,
        entry_id: str,
        device_info: Dict[str, Any],
        device_id: str,
        key: str,
        icon: str,
    ):
        super().__init__(coordinator)
        self.hass = hass
        self._entry_id = entry_id
        self._device_info = device_info
        self._device_id = device_id
        self._key = key
        self._attr_icon = icon
        self._attr_translation_key = key
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def device_info(self):
        return self._device_info

    async def async_press(self) -> None:
        client = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if client is None:
            raise HomeAssistantError("The integration was reloaded; try again")
        try:
            status = await self.hass.async_add_executor_job(
                getattr(client, self._key), self._device_id
            )
        except Exception as err:
            _LOGGER.error("%s failed: %s", self._key, err)
            raise HomeAssistantError(
                f"Could not {self._key.replace('_', ' ')}: {err}"
            ) from err
        _LOGGER.info("%s sent, cloud reports chargeStatus %s", self._key, status)
        await self.coordinator.async_request_refresh()
