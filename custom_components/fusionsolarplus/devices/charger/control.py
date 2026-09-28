"""Shared base for charger setting entities: write, read back, retry once."""

import asyncio
import logging
from typing import Any, Callable, Dict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ...const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SETTLE_SECONDS = 3
MAX_ATTEMPTS = 2


class ChargerSettingEntity(CoordinatorEntity):
    """One writable charger config signal, verified after every change."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        hass: HomeAssistant,
        entry_id: str,
        device_info: Dict[str, Any],
        device_id: str,
        device_name: str,
        signal_id: int,
        key: str,
        name: str,
    ):
        super().__init__(coordinator)
        self.hass = hass
        self._entry_id = entry_id
        self._device_info = device_info
        self._device_id = device_id
        self._signal_id = signal_id
        self._busy = False
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_name = f"{device_name} {name}"

    @property
    def device_info(self):
        return self._device_info

    @property
    def raw_value(self) -> str | None:
        control = (self.coordinator.data or {}).get("control")
        if not control:
            return None
        return control.get("settings", {}).get(self._signal_id)

    @property
    def available(self) -> bool:
        return (
            not self._busy
            and self.coordinator.last_update_success
            and self.raw_value is not None
        )

    async def _write(self, value: str, matches: Callable[[str], bool]) -> None:
        """Write `value`, then confirm via a fresh read (retry once)."""
        if self._busy:
            raise HomeAssistantError("This setting is already being changed")

        self._busy = True
        self.async_write_ha_state()
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                client = self.hass.data[DOMAIN][self._entry_id]
                try:
                    await self.hass.async_add_executor_job(
                        client.set_charger_setting,
                        self._device_id,
                        self._signal_id,
                        value,
                    )
                except Exception as err:
                    _LOGGER.error(
                        "Writing signal %s=%s failed: %s", self._signal_id, value, err
                    )
                    if attempt == MAX_ATTEMPTS:
                        raise HomeAssistantError(f"Could not set {value}: {err}") from err
                    continue

                await asyncio.sleep(SETTLE_SECONDS)
                await self.coordinator.async_refresh()
                current = self.raw_value
                if current is not None and matches(current):
                    return
                _LOGGER.warning(
                    "Signal %s reads %r after writing %r (attempt %d/%d)",
                    self._signal_id,
                    current,
                    value,
                    attempt,
                    MAX_ATTEMPTS,
                )
            raise HomeAssistantError(
                f"Signal {self._signal_id} did not change to {value} after {MAX_ATTEMPTS} attempts"
            )
        finally:
            self._busy = False
            self.async_write_ha_state()
