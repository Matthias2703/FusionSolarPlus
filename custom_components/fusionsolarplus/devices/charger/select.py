"""Select platform for Charger devices: charging mode and cable lock."""

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
from .backup import make_plan_backup
from .control import (
    MAX_ATTEMPTS,
    ChargerSettingEntity,
    confirm,
)
from .const import (
    CHARGING_MODE_OPTIONS,
    CONNECTOR_LOCK_OPTIONS,
    MODE_CHARGE_NOW,
    MODE_PV_SURPLUS,
    MODE_SCHEDULED,
    SIGNAL_CONNECTOR_LOCK,
)

_LOGGER = logging.getLogger(__name__)


class ChargerSelectHandler(BaseDeviceHandler):
    """Handler for the charging-mode and cable-lock selects."""

    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        return [
            FusionSolarChargingModeSelect(
                coordinator,
                self.hass,
                self.entry.entry_id,
                self.device_info,
                self.device_id,
            ),
            FusionSolarConnectorLockSelect(
                coordinator,
                self.hass,
                self.entry.entry_id,
                self.device_info,
                self.device_id,
                SIGNAL_CONNECTOR_LOCK,
                "connector_lock_control",
            ),
        ]


class FusionSolarChargingModeSelect(CoordinatorEntity, SelectEntity):
    """Charge now / PV surplus / Scheduled, confirmed after every change.

    The app's three modes are two cloud settings: the schedule switch and the
    working mode. "Scheduled" wins whenever the schedule is on, whatever the
    working mode says; the working mode is exposed as an attribute.
    """

    _attr_icon = "mdi:ev-station"
    _attr_has_entity_name = True
    _attr_options = CHARGING_MODE_OPTIONS
    _attr_translation_key = "charging_mode"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        hass: HomeAssistant,
        entry_id: str,
        device_info: Dict[str, Any],
        device_id: str,
    ):
        super().__init__(coordinator)
        self.hass = hass
        self._entry_id = entry_id
        self._device_info = device_info
        self._device_id = device_id
        self._pending: str | None = None
        self._writing = False
        self._attr_unique_id = f"{device_id}_charging_mode_select"

    @property
    def device_info(self):
        return self._device_info

    @property
    def _control(self) -> dict | None:
        return (self.coordinator.data or {}).get("control")

    @property
    def cloud_option(self) -> str | None:
        """The mode the cloud currently reports; None if it cannot be read."""
        control = self._control
        if not control:
            return None
        if control["schedule_on"]:
            return MODE_SCHEDULED
        if control["working_mode"] == "1":
            return MODE_PV_SURPLUS
        if control["working_mode"] == "0":
            return MODE_CHARGE_NOW
        return None

    @property
    def current_option(self) -> str | None:
        return self._pending if self._pending is not None else self.cloud_option

    @property
    def extra_state_attributes(self) -> dict:
        control = self._control
        return {"working_mode": control["working_mode"] if control else None}

    @property
    def available(self) -> bool:
        if self._pending is not None:
            return True
        return self.coordinator.last_update_success and self.cloud_option is not None

    def _write_state(self) -> None:
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    def _apply(self, option: str) -> None:
        """Blocking: send the writes for one option (runs in the executor).

        Both steps are idempotent on the API side, so nothing depends on
        possibly stale coordinator data. If the second step fails after the
        first succeeded the schedule stays on, which is why the error says so.
        """
        client = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if client is None:
            raise HomeAssistantError(
                "The integration was reloaded while writing; check the mode"
            )
        backup = make_plan_backup(self.hass)
        if option == MODE_SCHEDULED:
            client.set_charger_schedule_enabled(self._device_id, True, backup)
            return
        client.set_charger_working_mode(
            self._device_id, "1" if option == MODE_PV_SURPLUS else "0"
        )
        try:
            client.set_charger_schedule_enabled(self._device_id, False, backup)
        except Exception as err:
            raise HomeAssistantError(
                f"The working mode was set, but switching the schedule off failed: {err}"
            ) from err

    async def async_select_option(self, option: str) -> None:
        if option not in CHARGING_MODE_OPTIONS:
            raise HomeAssistantError(f"Unknown charging mode: {option}")
        if self._writing:
            raise HomeAssistantError("Charging mode is already being changed")

        self._writing = True
        self._pending = option
        self._write_state()
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    await self.hass.async_add_executor_job(self._apply, option)
                except HomeAssistantError:
                    raise
                except Exception as err:
                    _LOGGER.error("Setting charging mode '%s' failed: %s", option, err)
                    raise HomeAssistantError(
                        f"Could not set charging mode '{option}': {err}"
                    ) from err

                if await confirm(
                    self.coordinator,
                    self._device_id,
                    lambda: self.cloud_option == option,
                ):
                    return
                _LOGGER.warning(
                    "Charging mode reads '%s' instead of '%s' (attempt %d/%d)",
                    self.cloud_option,
                    option,
                    attempt,
                    MAX_ATTEMPTS,
                )
            raise HomeAssistantError(
                f"Charging mode did not change to '{option}' after {MAX_ATTEMPTS} attempts"
            )
        finally:
            self._pending = None
            self._writing = False
            self._write_state()


class FusionSolarConnectorLockSelect(ChargerSettingEntity, SelectEntity):
    """When the cable is locked: manually / while charging / once inserted."""

    _attr_icon = "mdi:lock"
    _attr_options = list(CONNECTOR_LOCK_OPTIONS.values())
    _attr_translation_key = "cable_lock"

    @property
    def current_option(self) -> str | None:
        return CONNECTOR_LOCK_OPTIONS.get(self.display_value)

    async def async_select_option(self, option: str) -> None:
        by_key = {key: cloud for cloud, key in CONNECTOR_LOCK_OPTIONS.items()}
        if option not in by_key:
            raise HomeAssistantError(f"Unknown lock option: {option}")
        cloud_value = by_key[option]
        await self._write(cloud_value, lambda raw: raw == cloud_value)
