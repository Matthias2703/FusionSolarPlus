from datetime import datetime, timezone
from typing import Callable, Dict, Any, List

from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.components.sensor import ENTITY_ID_FORMAT

from ...device_handler import BaseDeviceHandler
from .const import (
    CHARGING_PILE_SIGNALS,
    CHARGER_DEVICE_SIGNALS,
)


class ChargerDeviceHandler(BaseDeviceHandler):
    """Handler for Charger devices"""

    async def _async_get_data(self) -> Dict[str, Any]:
        async def fetch_charger_data(client):
            return await self.hass.async_add_executor_job(
                client.get_charger_data, self.device_id, self.hass.config.time_zone
            )

        return await self._get_client_and_retry(fetch_charger_data)

    def create_entities(self, coordinator: DataUpdateCoordinator) -> List:
        entities = []
        unique_ids = set()

        if not coordinator.data:
            return entities

        for signal_type_id, signals_data in coordinator.data.get(
            "raw_data", {}
        ).items():
            if not isinstance(signals_data, list):
                continue

            signal_list = self._get_signal_list_for_type(signals_data)

            if not signal_list:
                continue

            for signal_config in signal_list:
                matching_signal = next(
                    (s for s in signals_data if s.get("id") == signal_config["id"]),
                    None,
                )

                if matching_signal:
                    unique_id = f"{list(self.device_info['identifiers'])[0][1]}_{signal_type_id}_{signal_config['id']}"
                    if unique_id not in unique_ids:
                        entity = FusionSolarChargerSensor(
                            coordinator,
                            signal_config["id"],
                            signal_config.get("custom_name", signal_config["name"]),
                            signal_config.get("unit", None),
                            self.device_info,
                            signal_config.get("device_class"),
                            signal_config.get("state_class"),
                            signal_type_id,
                        )
                        entities.append(entity)
                        unique_ids.add(unique_id)

        entities.extend(self._create_history_entities(coordinator))
        entities.extend(self._create_setting_sensors(coordinator))
        return entities

    def _create_setting_sensors(self, coordinator: DataUpdateCoordinator) -> List:
        """Read-only view of the PV thresholds the app does not display."""
        specs = [
            (20007, "pv_start_surplus", "PV Start Surplus", None),
            (20006, "pv_max_grid_power", "PV Max Grid Power", "kW"),
        ]
        return [
            FusionSolarChargerSettingSensor(
                coordinator, self.device_info, signal_id, key, name, unit
            )
            for signal_id, key, name, unit in specs
        ]

    def _create_history_entities(self, coordinator: DataUpdateCoordinator) -> List:
        """Sensors built from the charge record list (read-only)."""

        def last(field: str, convert: Callable = lambda v: v):
            def extract(history: dict):
                record = history.get("last")
                if not record or record.get(field) is None:
                    return None
                return convert(record[field])

            return extract

        def to_time(value):
            return datetime.fromtimestamp(int(float(value)), tz=timezone.utc)

        mode_names = {0: "Normal charge", 1: "PV surplus"}
        specs = [
            ("history_total", "Charge Sessions (180 Days)", lambda h: h.get("total"), None, None, SensorStateClass.MEASUREMENT),
            ("history_last_energy", "Last Session Energy", last("totalPower", float), "kWh", SensorDeviceClass.ENERGY, None),
            ("history_last_duration", "Last Session Duration", last("totalTime", lambda v: int(float(v))), "min", SensorDeviceClass.DURATION, None),
            ("history_last_start", "Last Session Start", last("startTime", to_time), None, SensorDeviceClass.TIMESTAMP, None),
            ("history_last_mode", "Last Session Mode", last("chargeMode", lambda v: mode_names.get(int(v), str(v))), None, None, None),
        ]
        return [
            FusionSolarChargeHistorySensor(
                coordinator, self.device_info, key, name, extract, unit, device_class, state_class
            )
            for key, name, extract, unit, device_class, state_class in specs
        ]

    def _get_signal_list_for_type(self, signals_data):
        """Determine which signal list to use based on the signals present in the data"""
        if not signals_data:
            return None

        # Build a map of signal names for easier checking
        signal_names = {
            signal.get("name") for signal in signals_data if signal.get("name")
        }

        # Check for "Charging Connector No." to identify charging pile data
        if "Charging Connector No." in signal_names:
            return CHARGING_PILE_SIGNALS

        # Check for "Software Version" to identify charger device data
        if "Software Version" in signal_names:
            return CHARGER_DEVICE_SIGNALS

        return None


class FusionSolarChargerSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Charger devices."""

    def __init__(
        self,
        coordinator,
        signal_id,
        name,
        unit,
        device_info,
        device_class=None,
        state_class=None,
        signal_type_id=None,
    ):
        super().__init__(coordinator)
        self._signal_id = signal_id
        self._signal_type_id = signal_type_id
        self._attr_name = name
        self._base_unit = unit
        self._attr_device_info = device_info
        self._attr_unique_id = (
            f"{list(device_info['identifiers'])[0][1]}_{signal_type_id}_{signal_id}"
        )
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        device_id = list(device_info["identifiers"])[0][1]
        safe_name = name.lower().replace(" ", "_")
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, f"fsp_{device_id}_{safe_name}", hass=coordinator.hass
        )

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._base_unit

    @property
    def native_value(self):
        """Return normalized charger value from coordinator payload."""
        data = self.coordinator.data
        if not data:
            return None
        value = data.get("value_map", {}).get(
            (self._signal_type_id, int(self._signal_id))
        )
        if value is None:
            return None
        if self._attr_device_class == SensorDeviceClass.ENUM:
            return str(value)
        return value

    @property
    def available(self):
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )


class FusionSolarChargeHistorySensor(CoordinatorEntity, SensorEntity):
    """One value derived from the charge record list."""

    def __init__(
        self,
        coordinator,
        device_info,
        key,
        name,
        extract,
        unit=None,
        device_class=None,
        state_class=None,
    ):
        super().__init__(coordinator)
        self._extract = extract
        device_id = list(device_info["identifiers"])[0][1]
        self._attr_name = name
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT,
            f"fsp_{device_id}_{name.lower().replace(' ', '_')}",
            hass=coordinator.hass,
        )

    @property
    def native_value(self):
        history = (self.coordinator.data or {}).get("history")
        if not history:
            return None
        return self._extract(history)

    @property
    def available(self):
        return self.coordinator.last_update_success and bool(
            (self.coordinator.data or {}).get("history")
        )


class FusionSolarChargerSettingSensor(CoordinatorEntity, SensorEntity):
    """A charger config value shown read-only (diagnostic)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, signal_id, key, name, unit=None):
        super().__init__(coordinator)
        device_id = list(device_info["identifiers"])[0][1]
        self._signal_id = signal_id
        self._attr_name = name
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device_id}_{key}_sensor"
        self._attr_native_unit_of_measurement = unit
        if unit == "kW":
            self._attr_device_class = SensorDeviceClass.POWER
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT,
            f"fsp_{device_id}_{name.lower().replace(' ', '_')}",
            hass=coordinator.hass,
        )

    @property
    def native_value(self):
        control = (self.coordinator.data or {}).get("control")
        raw = control.get("settings", {}).get(self._signal_id) if control else None
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None
