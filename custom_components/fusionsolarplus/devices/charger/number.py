"""Number platform for Charger devices (PV surplus thresholds, power limit)."""

from typing import List

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ...device_handler import BaseDeviceHandler
from .control import ChargerSettingEntity
from .const import SIGNAL_MAX_GRID_POWER, SIGNAL_POWER_LIMIT, SIGNAL_SURPLUS_START

# (signal id, unique key, name, min kW, max kW). The power limit range is the
# one the app reports; the other two are conservative and the cloud rejects
# anything it does not accept.
NUMBERS = [
    (SIGNAL_SURPLUS_START, "surplus_power_to_start", "Surplus Power to Start Charging", 1.4, 11.0),
    (SIGNAL_MAX_GRID_POWER, "max_grid_power", "Max Charging Power from Grid", 0.0, 11.0),
    (SIGNAL_POWER_LIMIT, "charge_power_limit", "Charge Power Upper Limit", 4.1, 11.0),
]


class ChargerNumberHandler(BaseDeviceHandler):
    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        return [
            FusionSolarChargerNumber(
                coordinator,
                self.hass,
                self.entry.entry_id,
                self.device_info,
                self.device_id,
                self.device_name,
                signal_id,
                key,
                name,
                low,
                high,
            )
            for signal_id, key, name, low, high in NUMBERS
        ]


class FusionSolarChargerNumber(ChargerSettingEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = "kW"
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator,
        hass,
        entry_id,
        device_info,
        device_id,
        device_name,
        signal_id,
        key,
        name,
        low,
        high,
    ):
        super().__init__(
            coordinator,
            hass,
            entry_id,
            device_info,
            device_id,
            device_name,
            signal_id,
            key,
            name,
        )
        self._attr_native_min_value = low
        self._attr_native_max_value = high

    @property
    def native_value(self) -> float | None:
        raw = self.raw_value
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        value = round(value, 1)
        await self._write(
            str(value), lambda raw: abs(float(raw) - value) < 0.05
        )
