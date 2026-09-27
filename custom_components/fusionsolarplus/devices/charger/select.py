"""Select platform for Charger devices (charging mode: Charge Now / Scheduled / PV Surplus)."""

import asyncio
import logging
from typing import Dict, Any, List

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ...device_handler import BaseDeviceHandler
from ...const import DOMAIN
from ...api.devices.charger_api import get_charging_pile_signal_value
from .const import CHARGING_MODE_SIGNAL_ID, CHARGING_MODE_OPTIONS

_LOGGER = logging.getLogger(__name__)

WORKING_MODE_SIGNAL_ID = 455780020  # "Reported Working Mode" (read-back only)


class ChargerModeSelectHandler(BaseDeviceHandler):
    """Handler for the charging-mode select entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: Dict[str, Any],
    ):
        super().__init__(hass, entry, device_info)

    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        """Create the mode select entity, unless the signal id/options are unknown."""
        if CHARGING_MODE_SIGNAL_ID is None or not CHARGING_MODE_OPTIONS:
            _LOGGER.warning(
                "Charging mode signal id/options are not configured yet - "
                "skipping the charging mode select for %s. See "
                "devices/charger/const.py for how to capture them from the "
                "FusionSolar portal.",
                self.device_name,
            )
            return []

        client = self.hass.data[DOMAIN][self.entry.entry_id]
        password = self.entry.options.get("password", self.entry.data.get("password"))

        return [
            FusionSolarChargingModeSelect(
                coordinator,
                self.hass,
                self.device_info,
                self.device_id,
                self.device_name,
                client,
                password,
            )
        ]


class FusionSolarChargingModeSelect(CoordinatorEntity, SelectEntity):
    """Switch the charger between Charge Now / Scheduled / PV Surplus."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        hass: HomeAssistant,
        device_info: Dict[str, Any],
        device_id: str,
        device_name: str,
        client,
        password: str,
    ):
        super().__init__(coordinator)
        self.hass = hass
        self._device_info = device_info
        self._device_id = device_id
        self._client = client
        self._password = password
        self._is_switching = False
        self._last_option = None
        self._attr_unique_id = f"{device_id}_charging_mode_select"
        self._attr_name = f"{device_name} Charging Mode"
        self._attr_icon = "mdi:ev-plug-type2"
        self._attr_options = list(CHARGING_MODE_OPTIONS.values())
        self._value_by_option = {v: k for k, v in CHARGING_MODE_OPTIONS.items()}

    @property
    def device_info(self):
        return self._device_info

    @property
    def available(self) -> bool:
        return not self._is_switching and self.coordinator.last_update_success

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data:
            raw_value = get_charging_pile_signal_value(
                self.coordinator.data.get("raw_data", {}), WORKING_MODE_SIGNAL_ID
            )
            if raw_value is not None:
                option = CHARGING_MODE_OPTIONS.get(str(raw_value))
                if option is not None:
                    self._last_option = option
                    return option
        return self._last_option

    async def async_select_option(self, option: str) -> None:
        """Switch charging mode and verify it actually took effect.

        The native app is reported unreliable exactly here (mode flips back
        on its own), so instead of a fire-and-forget command we re-read the
        working-mode signal after a short delay and retry once if it hasn't
        changed.
        """
        value = self._value_by_option.get(option)
        if value is None:
            _LOGGER.error("Unknown charging mode option: %s", option)
            return

        if self._is_switching:
            _LOGGER.warning("Charging mode is already being changed. Please wait.")
            return

        self._is_switching = True
        self.async_write_ha_state()

        try:
            for attempt in range(2):
                await self.hass.async_add_executor_job(
                    self._client.toggle_device,
                    self._device_id,
                    str(CHARGING_MODE_SIGNAL_ID),
                    self._password,
                    value,
                )
                await asyncio.sleep(10)
                await self.coordinator.async_request_refresh()
                if self.current_option == option:
                    break
                _LOGGER.warning(
                    "Charging mode did not report '%s' after attempt %d/2, retrying",
                    option,
                    attempt + 1,
                )
            else:
                _LOGGER.error(
                    "Charging mode still not confirmed as '%s' after retry", option
                )
        finally:
            self._is_switching = False
            self.async_write_ha_state()
