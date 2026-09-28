"""Shared test setup.

The tests run without Home Assistant. The package `__init__` files (which pull
in the whole integration) are replaced by empty modules, and the few Home
Assistant classes the charger code inherits from are replaced by small fakes,
so only the charger API layer and the charger entity logic are exercised.
"""

import asyncio
import enum
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components"
FUSION = ROOT / "fusionsolarplus"


def _package(name: str, path: pathlib.Path) -> None:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


class _AnyAttr:
    """Stands in for enum-like classes: every attribute is just its own name."""

    def __getattr__(self, name):
        return name


class HomeAssistantError(Exception):
    pass


class _Coordinator:
    def __init__(self, data=None):
        self.data = data
        self.last_update_success = True
        self.refreshes = 0

    async def async_refresh(self):
        self.refreshes += 1


class _CoordinatorEntity:
    hass = None
    entity_id = None

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.states_written = 0

    def async_write_ha_state(self):
        self.states_written += 1


class _Entity:
    pass


class _EntityCategory(enum.Enum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class _BaseDeviceHandler:
    def __init__(self, hass, entry, device_info):
        self.hass = hass
        self.entry = entry
        self.device_info = device_info


def _install_home_assistant_fakes() -> None:
    _module("homeassistant")
    _module("homeassistant.const", EntityCategory=_EntityCategory)
    _module("homeassistant.core", HomeAssistant=object)
    _module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    _module("homeassistant.helpers")
    _module(
        "homeassistant.helpers.update_coordinator",
        CoordinatorEntity=_CoordinatorEntity,
        DataUpdateCoordinator=_Coordinator,
    )
    _module("homeassistant.helpers.storage", Store=object)
    _module("homeassistant.components")
    _module("homeassistant.components.select", SelectEntity=_Entity)
    _module("homeassistant.components.switch", SwitchEntity=_Entity)
    _module(
        "homeassistant.components.sensor",
        SensorDeviceClass=_AnyAttr(),
        SensorStateClass=_AnyAttr(),
        SensorEntity=_Entity,
        ENTITY_ID_FORMAT="sensor.{}",
    )


for _name, _path in [
    ("custom_components", ROOT),
    ("custom_components.fusionsolarplus", FUSION),
    ("custom_components.fusionsolarplus.api", FUSION / "api"),
    ("custom_components.fusionsolarplus.api.devices", FUSION / "api" / "devices"),
    ("custom_components.fusionsolarplus.devices", FUSION / "devices"),
    (
        "custom_components.fusionsolarplus.devices.charger",
        FUSION / "devices" / "charger",
    ),
]:
    _package(_name, _path)

_install_home_assistant_fakes()
_module(
    "custom_components.fusionsolarplus.device_handler",
    BaseDeviceHandler=_BaseDeviceHandler,
)


def run(coroutine):
    """Run one coroutine to completion (the suite does not need pytest-asyncio)."""
    return asyncio.run(coroutine)
