import logging
from functools import partial

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .api.client import FusionSolarClient
from .api.devices.charger_api import clear_caches
from .api.exceptions import AuthenticationException

from .const import CONF_CHARGER_CONTROL, DEFAULT_CHARGER_CONTROL, DOMAIN
from .devices.charger.cleanup import stale_entity_ids
from .sensor import DeviceHandlerFactory

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "switch", "select", "button"]


async def async_setup_entry(hass, entry):
    entry.async_on_unload(entry.add_update_listener(update_listener))

    username = entry.options.get("username", entry.data["username"])
    password = entry.options.get("password", entry.data["password"])
    subdomain = entry.options.get("subdomain", entry.data.get("subdomain", "uni001eu5"))

    try:
        client = await hass.async_add_executor_job(
            partial(
                FusionSolarClient,
                username,
                password,
                captcha_model_path=hass,
                huawei_subdomain=subdomain,
            )
        )
    except AuthenticationException as err:
        raise ConfigEntryAuthFailed(f"FusionSolar login failed: {err}") from err
    except Exception as err:
        raise ConfigEntryNotReady(f"FusionSolar is not reachable: {err}") from err

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][entry.entry_id] = client

    device_id = entry.data.get("device_id")
    device_name = entry.data.get("device_name")
    device_type = entry.data.get("device_type")

    device_info = {
        "identifiers": {(DOMAIN, str(device_id))},
        "name": device_name,
        "manufacturer": "FusionSolar",
        "model": device_type or "Unknown",
    }
    hass.data[DOMAIN][f"{entry.entry_id}_device_info"] = device_info

    try:
        sensor_handler = DeviceHandlerFactory.create_handler(hass, entry, device_info)
        coordinator = await sensor_handler.create_coordinator()

        hass.data[DOMAIN][f"{entry.entry_id}_coordinator"] = coordinator
        hass.data[DOMAIN][f"{entry.entry_id}_sensor_handler"] = sensor_handler
    except ConfigEntryNotReady:
        raise
    except Exception as e:
        _LOGGER.error("Failed to create coordinator for device %s: %s", device_name, e)
        return False

    device_registry = async_get_device_registry(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, str(entry.data["device_id"]))},
        manufacturer="FusionSolar",
        name=entry.data["device_name"],
        model=entry.data["device_type"],
    )

    if device_type == "Charger":
        registry = er.async_get(hass)
        for entity_id in stale_entity_ids(
            er.async_entries_for_config_entry(registry, entry.entry_id),
            str(device_id),
            entry.options.get(CONF_CHARGER_CONTROL, DEFAULT_CHARGER_CONTROL),
        ):
            registry.async_remove(entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def update_listener(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        clear_caches(entry.data.get("device_id"))
        hass.data[DOMAIN].pop(f"{entry.entry_id}_coordinator", None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_device_info", None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_sensor_handler", None)
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
