"""Persistent backup of the charging plans taken before every schedule switch."""

from datetime import datetime, timezone
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

STORAGE_KEY = "fusionsolarplus_plan_backup"
STORAGE_VERSION = 1
MAX_BACKUPS = 5


async def async_store_plan_backup(
    hass: HomeAssistant, device_dn: str, plans: list[dict], schedule_on: bool
) -> None:
    """Keep the last few plan lists, newest last, in .storage."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {"backups": []}
    data["backups"].append(
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "device": device_dn,
            "schedule_on": schedule_on,
            "plans": plans,
        }
    )
    data["backups"] = data["backups"][-MAX_BACKUPS:]
    await store.async_save(data)


def make_plan_backup(
    hass: HomeAssistant,
) -> Callable[[str, list[dict], bool], Any]:
    """A thread-safe callback for the API layer, which runs in the executor."""

    def backup(device_dn: str, plans: list[dict], schedule_on: bool) -> None:
        hass.loop.call_soon_threadsafe(
            hass.async_create_task,
            async_store_plan_backup(hass, device_dn, list(plans), schedule_on),
        )

    return backup
