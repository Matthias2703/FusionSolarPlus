"""Number platform for Charger devices (charge power limit)."""

from typing import List

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ...device_handler import BaseDeviceHandler
from .control import ChargerSettingEntity
from .const import SIGNAL_POWER_LIMIT

# (signal id, unique key, name, fallback min kW, fallback max kW). The real
# range is read from the cloud on every refresh, so a site approved for 22 kW
# gets 22 and everyone else stays at what the installer allowed; the fallback
# only applies until the first read. The two PV values (20006/20007) are not
# editable on purpose: the app flags them displayExp=false, i.e. internal
# defaults it never shows.
NUMBERS = [
    (SIGNAL_POWER_LIMIT, "charge_power_limit", "Power Limit", 4.1, 11.0),
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
        self._fallback_range = (low, high)

    @property
    def _range(self) -> tuple[float, float]:
        control = (self.coordinator.data or {}).get("control") or {}
        return control.get("ranges", {}).get(self._signal_id, self._fallback_range)

    @property
    def native_min_value(self) -> float:
        return self._range[0]

    @property
    def native_max_value(self) -> float:
        return self._range[1]

    @property
    def native_value(self) -> float | None:
        raw = self.display_value
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        value = round(value, 1)

        def same(raw: str) -> bool:
            try:
                return abs(float(raw) - value) < 0.05
            except ValueError:
                return False

        await self._write(str(value), same)
