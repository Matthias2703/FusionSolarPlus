"""Tests for the charger entity logic (write, confirm by read-back, retry)."""

import importlib
import types

import pytest

from conftest import HomeAssistantError, _Coordinator, run

DOMAIN = "fusionsolarplus"
PKG = "custom_components.fusionsolarplus.devices.charger"
control = importlib.import_module(f"{PKG}.control")
select = importlib.import_module(f"{PKG}.select")
cleanup = importlib.import_module(f"{PKG}.cleanup")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(control, "SETTLE_SECONDS", 0)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.on_write = None

    def set_charger_setting(self, device_id, signal_id, value):
        self.calls.append(("setting", signal_id, value))
        if self.fail:
            raise self.fail
        if self.on_write:
            self.on_write(len([c for c in self.calls if c[0] == "setting"]))

    def set_charger_working_mode(self, device_id, value):
        self.calls.append(("mode", value))

    def set_charger_schedule_enabled(self, device_id, enabled, backup=None):
        self.calls.append(("schedule", enabled, callable(backup)))
        if self.fail_schedule:
            raise self.fail_schedule

    fail_schedule = None


class FakeHass:
    def __init__(self, client, entry_id="e1"):
        self.data = {DOMAIN: {entry_id: client}}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def coordinator(settings=None, schedule_on=False, working_mode="0"):
    c = _Coordinator(
        {
            "control": {
                "settings": settings if settings is not None else {},
                "schedule_on": schedule_on,
                "working_mode": working_mode,
            }
        }
    )
    return c


def setting_entity(coord, client, entry_id="e1", signal_id=538976529):
    entity = control.ChargerSettingEntity(
        coord,
        FakeHass(client),
        entry_id,
        {"identifiers": {("d", "1")}},
        "NE=1",
        signal_id,
        "key",
    )
    entity.hass = FakeHass(client, entry_id)
    entity.entity_id = "switch.test"
    return entity


def test_confirm_polls_until_the_check_passes():
    coord = coordinator()
    seen = []

    def check():
        seen.append(coord.refreshes)
        return coord.refreshes >= 2

    assert run(control.confirm(coord, "NE=1", check)) is True
    assert seen == [1, 2]


def test_confirm_gives_up_after_the_configured_checks():
    coord = coordinator()
    assert run(control.confirm(coord, "NE=1", lambda: False)) is False
    assert coord.refreshes == control.CONFIRM_CHECKS


def test_a_confirmed_write_clears_the_pending_value():
    coord = coordinator({538976529: "0"})
    client = FakeClient()
    client.on_write = lambda n: coord.data["control"]["settings"].update(
        {538976529: "1"}
    )
    entity = setting_entity(coord, client)
    run(entity._write("1", lambda raw: raw == "1"))
    assert client.calls == [("setting", 538976529, "1")]
    assert entity._pending is None and not entity._writing
    assert entity.states_written >= 2


def test_an_unconfirmed_write_is_repeated_once_then_succeeds():
    coord = coordinator({538976529: "0"})
    client = FakeClient()

    def on_write(number):
        if number == 2:
            coord.data["control"]["settings"][538976529] = "1"

    client.on_write = on_write
    entity = setting_entity(coord, client)
    run(entity._write("1", lambda raw: raw == "1"))
    assert len(client.calls) == 2


def test_a_write_that_never_shows_up_fails_after_the_attempts():
    coord = coordinator({538976529: "0"})
    client = FakeClient()
    entity = setting_entity(coord, client)
    with pytest.raises(HomeAssistantError, match="did not change"):
        run(entity._write("1", lambda raw: raw == "1"))
    assert len(client.calls) == control.MAX_ATTEMPTS
    assert entity._pending is None and not entity._writing


def test_a_failing_request_is_reported_and_not_retried():
    coord = coordinator({538976529: "0"})
    client = FakeClient()
    client.fail = RuntimeError("cloud says no")
    entity = setting_entity(coord, client)
    with pytest.raises(HomeAssistantError, match="cloud says no"):
        run(entity._write("1", lambda raw: raw == "1"))
    assert len(client.calls) == 1 and entity._pending is None


def test_a_write_after_a_reload_is_refused():
    coord = coordinator({538976529: "0"})
    entity = setting_entity(coord, FakeClient())
    entity.hass.data[DOMAIN].clear()
    with pytest.raises(HomeAssistantError, match="reloaded"):
        run(entity._write("1", lambda raw: raw == "1"))


def test_two_writes_at_once_are_refused():
    entity = setting_entity(coordinator({538976529: "0"}), FakeClient())
    entity._writing = True
    with pytest.raises(HomeAssistantError, match="already"):
        run(entity._write("1", lambda raw: True))


def test_the_entity_stays_available_while_a_write_runs_even_if_a_refresh_fails():
    coord = coordinator({538976529: "0"})
    entity = setting_entity(coord, FakeClient())
    coord.last_update_success = False
    assert entity.available is False
    entity._pending = "1"
    assert entity.available is True
    assert entity.display_value == "1"


def mode_select(coord, client):
    entity = select.FusionSolarChargingModeSelect(
        coord, FakeHass(client), "e1", {"identifiers": {("d", "1")}}, "NE=1"
    )
    entity.entity_id = "select.test"
    return entity


@pytest.mark.parametrize(
    "schedule_on, working_mode, expected",
    [
        (True, "0", "scheduled"),
        (True, "1", "scheduled"),
        (False, "1", "pv_surplus"),
        (False, "0", "charge_now"),
        (False, None, None),
    ],
)
def test_the_three_modes_are_read_from_schedule_and_working_mode(
    schedule_on, working_mode, expected
):
    entity = mode_select(
        coordinator(schedule_on=schedule_on, working_mode=working_mode), FakeClient()
    )
    assert entity.cloud_option == expected


def test_choosing_scheduled_only_switches_the_schedule_on():
    client = FakeClient()
    mode_select(coordinator(), client)._apply("scheduled")
    assert client.calls == [("schedule", True, True)]


def test_choosing_pv_surplus_sets_the_mode_then_switches_the_schedule_off():
    client = FakeClient()
    mode_select(coordinator(), client)._apply("pv_surplus")
    assert client.calls == [("mode", "1"), ("schedule", False, True)]


def test_a_failing_schedule_switch_after_the_mode_change_says_so():
    client = FakeClient()
    client.fail_schedule = RuntimeError("plans look odd")
    with pytest.raises(HomeAssistantError, match="working mode was set"):
        mode_select(coordinator(), client)._apply("charge_now")
    assert client.calls[0] == ("mode", "0")


def test_choosing_a_mode_is_confirmed_by_reading_it_back():
    coord = coordinator(schedule_on=False, working_mode="0")
    client = FakeClient()
    entity = mode_select(coord, client)

    real_apply = entity._apply

    def apply_and_update(option):
        real_apply(option)
        coord.data["control"]["working_mode"] = "1"

    entity._apply = apply_and_update
    run(entity.async_select_option("pv_surplus"))
    assert entity._pending is None and entity.cloud_option == "pv_surplus"


def test_an_unknown_mode_is_rejected():
    with pytest.raises(HomeAssistantError, match="Unknown"):
        run(mode_select(coordinator(), FakeClient()).async_select_option("turbo"))


def entity_stub(domain, unique_id, entity_id):
    return types.SimpleNamespace(
        domain=domain, unique_id=unique_id, entity_id=entity_id
    )


ENTITIES = [
    entity_stub("select", "NE=1_charging_mode_select", "select.mode"),
    entity_stub("select", "NE=1_connector_lock_control", "select.lock"),
    entity_stub("switch", "NE=1_dynamic_charge_power", "switch.dyn"),
    entity_stub("sensor", "NE=1_charge_power_limit_sensor", "sensor.limit"),
    entity_stub("sensor", "NE=1_history_total", "sensor.history"),
    entity_stub("number", "NE=1_charge_power_limit", "number.old_limit"),
    entity_stub("sensor", "NE=1_10_20001", "sensor.status"),
]


def test_with_control_off_only_the_control_entities_are_removed():
    stale = cleanup.stale_entity_ids(ENTITIES, "NE=1", control_on=False)
    assert sorted(stale) == [
        "number.old_limit",
        "select.lock",
        "select.mode",
        "sensor.limit",
        "switch.dyn",
    ]


def test_with_control_on_only_the_legacy_number_entity_is_removed():
    assert cleanup.stale_entity_ids(ENTITIES, "NE=1", control_on=True) == [
        "number.old_limit"
    ]


def test_entities_of_other_devices_are_left_alone():
    assert cleanup.stale_entity_ids(ENTITIES, "NE=2", control_on=False) == []
