"""Switch platform for Charger devices (Dynamic Charge Power)."""

from typing import List

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ...device_handler import BaseDeviceHandler
from .control import ChargerSettingEntity
from .const import SIGNAL_DYNAMIC_POWER


class ChargerSwitchHandler(BaseDeviceHandler):
    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        return [
            FusionSolarDynamicPowerSwitch(
                coordinator,
                self.hass,
                self.entry.entry_id,
                self.device_info,
                self.device_id,
                self.device_name,
                SIGNAL_DYNAMIC_POWER,
                "dynamic_charge_power",
                "Dynamic Charge Power",
            )
        ]


class FusionSolarDynamicPowerSwitch(ChargerSettingEntity, SwitchEntity):
    _attr_icon = "mdi:solar-power"

    @property
    def is_on(self) -> bool | None:
        raw = self.raw_value
        return None if raw is None else raw == "1"

    async def async_turn_on(self, **kwargs) -> None:
        await self._write("1", lambda raw: raw == "1")

    async def async_turn_off(self, **kwargs) -> None:
        await self._write("0", lambda raw: raw == "0")
