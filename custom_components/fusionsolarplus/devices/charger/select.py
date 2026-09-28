"""Select platform for Charger devices: Charge now / PV surplus / Scheduled."""

import asyncio
import logging
from typing import Dict, Any, List

from homeassistant.core import HomeAssistant
from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ...device_handler import BaseDeviceHandler
from ...const import DOMAIN
from .control import ChargerSettingEntity
from .const import (
    CONNECTOR_LOCK_OPTIONS,
    SIGNAL_CONNECTOR_LOCK,
    CHARGING_MODE_OPTIONS,
    MODE_CHARGE_NOW,
    MODE_PV_SURPLUS,
    MODE_SCHEDULED,
)

_LOGGER = logging.getLogger(__name__)

SETTLE_SECONDS = 4
MAX_ATTEMPTS = 2


class ChargerSelectHandler(BaseDeviceHandler):
    """Handler for the charging-mode select."""

    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        return [
            FusionSolarChargingModeSelect(
                coordinator,
                self.hass,
                self.entry.entry_id,
                self.device_info,
                self.device_id,
                self.device_name,
            ),
            FusionSolarConnectorLockSelect(
                coordinator,
                self.hass,
                self.entry.entry_id,
                self.device_info,
                self.device_id,
                self.device_name,
                SIGNAL_CONNECTOR_LOCK,
                "connector_lock_control",
                "Connector Lock Control",
            ),
        ]


class FusionSolarChargingModeSelect(CoordinatorEntity, SelectEntity):
    """Charge now / PV surplus / Scheduled, verified after every change."""

    _attr_icon = "mdi:ev-station"
    _attr_options = CHARGING_MODE_OPTIONS

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        hass: HomeAssistant,
        entry_id: str,
        device_info: Dict[str, Any],
        device_id: str,
        device_name: str,
    ):
        super().__init__(coordinator)
        self.hass = hass
        self._entry_id = entry_id
        self._device_info = device_info
        self._device_id = device_id
        self._busy = False
        self._attr_unique_id = f"{device_id}_charging_mode_select"
        self._attr_name = f"{device_name} Charging Mode"

    @property
    def device_info(self):
        return self._device_info

    @property
    def available(self) -> bool:
        return not self._busy and self.coordinator.last_update_success

    @property
    def current_option(self) -> str | None:
        control = (self.coordinator.data or {}).get("control")
        if not control:
            return None
        if control["schedule_on"]:
            return MODE_SCHEDULED
        if control["working_mode"] == "1":
            return MODE_PV_SURPLUS
        if control["working_mode"] == "0":
            return MODE_CHARGE_NOW
        return None

    def _apply(self, option: str) -> None:
        """Blocking: send the writes for one option (runs in the executor)."""
        client = self.hass.data[DOMAIN][self._entry_id]
        if option == MODE_SCHEDULED:
            client.set_charger_schedule_enabled(self._device_id, True)
            return
        client.set_charger_working_mode(
            self._device_id, "1" if option == MODE_PV_SURPLUS else "0"
        )
        control = (self.coordinator.data or {}).get("control") or {}
        if control.get("schedule_on", True):
            client.set_charger_schedule_enabled(self._device_id, False)

    async def async_select_option(self, option: str) -> None:
        if option not in CHARGING_MODE_OPTIONS:
            raise HomeAssistantError(f"Unknown charging mode: {option}")
        if self._busy:
            raise HomeAssistantError("Charging mode is already being changed")

        self._busy = True
        self.async_write_ha_state()
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    await self.hass.async_add_executor_job(self._apply, option)
                except Exception as err:
                    _LOGGER.error("Setting charging mode '%s' failed: %s", option, err)
                    if attempt == MAX_ATTEMPTS:
                        raise HomeAssistantError(
                            f"Could not set charging mode '{option}': {err}"
                        ) from err
                    continue

                await asyncio.sleep(SETTLE_SECONDS)
                await self.coordinator.async_refresh()
                if self.current_option == option:
                    return
                _LOGGER.warning(
                    "Charging mode reads '%s' instead of '%s' (attempt %d/%d)",
                    self.current_option,
                    option,
                    attempt,
                    MAX_ATTEMPTS,
                )
            raise HomeAssistantError(
                f"Charging mode did not change to '{option}' after {MAX_ATTEMPTS} attempts"
            )
        finally:
            self._busy = False
            self.async_write_ha_state()


class FusionSolarConnectorLockSelect(ChargerSettingEntity, SelectEntity):
    """When the cable is locked: manually / while charging / once inserted."""

    _attr_icon = "mdi:lock"
    _attr_options = list(CONNECTOR_LOCK_OPTIONS.values())

    @property
    def current_option(self) -> str | None:
        return CONNECTOR_LOCK_OPTIONS.get(self.raw_value)

    async def async_select_option(self, option: str) -> None:
        by_label = {label: key for key, label in CONNECTOR_LOCK_OPTIONS.items()}
        if option not in by_label:
            raise HomeAssistantError(f"Unknown lock option: {option}")
        key = by_label[option]
        await self._write(key, lambda raw: raw == key)
