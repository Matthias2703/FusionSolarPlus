"""Shared base for charger setting entities: write, confirm by read-back, retry."""

import asyncio
import logging
from typing import Any, Callable, Dict

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ...api.devices.charger_api import invalidate_control_cache
from ...const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SETTLE_SECONDS = 3
CONFIRM_CHECKS = 3
MAX_ATTEMPTS = 2


async def confirm(
    coordinator: DataUpdateCoordinator,
    device_id: str,
    check: Callable[[], bool],
) -> bool:
    """Poll the cloud a few times until `check` passes.

    The cloud needs a moment to relay a change to the wallbox, so a value that
    is not visible yet is not treated as a failed write. The control cache is
    dropped before every refresh so each check reads fresh data.
    """
    for _ in range(CONFIRM_CHECKS):
        await asyncio.sleep(SETTLE_SECONDS)
        invalidate_control_cache(device_id)
        await coordinator.async_refresh()
        if check():
            return True
    return False


class ChargerSettingEntity(CoordinatorEntity):
    """One writable charger config signal, confirmed after every change."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        hass: HomeAssistant,
        entry_id: str,
        device_info: Dict[str, Any],
        device_id: str,
        signal_id: int,
        key: str,
    ):
        super().__init__(coordinator)
        self.hass = hass
        self._entry_id = entry_id
        self._device_info = device_info
        self._device_id = device_id
        self._signal_id = signal_id
        self._pending: str | None = None
        self._writing = False
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def device_info(self):
        return self._device_info

    @property
    def raw_value(self) -> str | None:
        """What the cloud last reported."""
        control = (self.coordinator.data or {}).get("control")
        if not control:
            return None
        return control.get("settings", {}).get(self._signal_id)

    @property
    def display_value(self) -> str | None:
        """The requested value while a write is in flight, else the cloud value."""
        return self._pending if self._pending is not None else self.raw_value

    @property
    def available(self) -> bool:
        if self._pending is not None:
            return True
        return self.coordinator.last_update_success and self.raw_value is not None

    def _write_state(self) -> None:
        """Write the state unless the entity was removed while a write ran."""
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    async def _write(self, value: str, matches: Callable[[str], bool]) -> None:
        """Write `value`, confirm via fresh reads, rewrite once if it never shows up."""
        if self._writing:
            raise HomeAssistantError("This setting is already being changed")

        self._writing = True
        self._pending = value
        self._write_state()
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                client = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
                if client is None:
                    raise HomeAssistantError(
                        "The integration was reloaded while writing; check the value"
                    )
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
                    raise HomeAssistantError(f"Could not set {value}: {err}") from err

                def confirmed() -> bool:
                    current = self.raw_value
                    return current is not None and matches(current)

                if await confirm(self.coordinator, self._device_id, confirmed):
                    return
                _LOGGER.warning(
                    "Signal %s still reads %r after writing %r (attempt %d/%d)",
                    self._signal_id,
                    self.raw_value,
                    value,
                    attempt,
                    MAX_ATTEMPTS,
                )
            raise HomeAssistantError(
                f"Signal {self._signal_id} did not change to {value} after {MAX_ATTEMPTS} attempts"
            )
        finally:
            self._pending = None
            self._writing = False
            self._write_state()
