"""Switch platform for Charger devices (start/stop the current charging session)."""

import asyncio
import logging
from typing import Dict, Any, List

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ...device_handler import BaseDeviceHandler
from ...const import DOMAIN
from ...api.devices.charger_api import get_charging_pile_signal_value
from .const import (
    CHARGING_START_SIGNAL_ID,
    CHARGING_STOP_SIGNAL_ID,
    CHARGING_ACTIVE_STATUS_VALUES,
)

_LOGGER = logging.getLogger(__name__)

WORKING_STATUS_SIGNAL_ID = 10004


class ChargerSwitchHandler(BaseDeviceHandler):
    """Handler for the charger start/stop switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: Dict[str, Any],
    ):
        super().__init__(hass, entry, device_info)

    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        """Create the charging switch, unless the control signal ids are unknown."""
        if CHARGING_START_SIGNAL_ID is None or CHARGING_STOP_SIGNAL_ID is None:
            _LOGGER.warning(
                "Charging start/stop signal ids are not configured yet - "
                "skipping the charging switch for %s. See "
                "devices/charger/const.py for how to capture them from the "
                "FusionSolar portal.",
                self.device_name,
            )
            return []

        client = self.hass.data[DOMAIN][self.entry.entry_id]
        password = self.entry.options.get("password", self.entry.data.get("password"))

        return [
            FusionSolarChargingSwitch(
                coordinator,
                self.hass,
                self.device_info,
                self.device_id,
                self.device_name,
                client,
                password,
            )
        ]


class FusionSolarChargingSwitch(CoordinatorEntity, SwitchEntity):
    """Start/stop the current charging session."""

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
        self._is_on = False
        self._is_toggling = False
        self._attr_unique_id = f"{device_id}_charging_switch"
        self._attr_name = f"{device_name} Charging"
        self._attr_icon = "mdi:ev-station"

    @property
    def device_info(self):
        return self._device_info

    @property
    def available(self) -> bool:
        return not self._is_toggling and self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        """Return whether a charging session is active.

        Until CHARGING_ACTIVE_STATUS_VALUES is filled in with real, observed
        "Working Status" values, this can't be read back from the device and
        falls back to the last state we commanded (optimistic, same pattern
        as the inverter power switch).
        """
        if not CHARGING_ACTIVE_STATUS_VALUES:
            return self._is_on

        if self.coordinator.data:
            raw_value = get_charging_pile_signal_value(
                self.coordinator.data.get("raw_data", {}), WORKING_STATUS_SIGNAL_ID
            )
            if raw_value is not None:
                self._is_on = str(raw_value) in CHARGING_ACTIVE_STATUS_VALUES
        return self._is_on

    async def _send_command(self, signal_id: int, new_state: bool):
        """Send a start/stop command and refresh once the cooldown elapses."""
        if self._is_toggling:
            _LOGGER.warning("Charger is already changing state. Please wait.")
            return

        self._is_toggling = True
        self._is_on = new_state
        self.async_write_ha_state()

        try:
            await self.hass.async_add_executor_job(
                self._client.toggle_device,
                self._device_id,
                str(signal_id),
                self._password,
                "0",
            )
        except Exception as e:
            _LOGGER.error(
                "Error sending charging %s command: %s",
                "start" if new_state else "stop",
                e,
            )
            self._is_on = not new_state
        finally:
            await asyncio.sleep(5)
            self._is_toggling = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs):
        await self._send_command(CHARGING_START_SIGNAL_ID, True)

    async def async_turn_off(self, **kwargs):
        await self._send_command(CHARGING_STOP_SIGNAL_ID, False)
