"""Tests for the charger API layer.

These run without Home Assistant: the package __init__ files are stubbed so
only api/values.py and api/devices/charger_api.py are imported. Response
bodies mirror what the FusionSolar app receives.
"""

import importlib
import json
import pathlib

import pytest

charger_api = importlib.import_module(
    "custom_components.fusionsolarplus.api.devices.charger_api"
)
values = importlib.import_module("custom_components.fusionsolarplus.api.values")

PLANS = [
    {
        "isValid": True,
        "isRepeat": True,
        "repeatPeriod": 127,
        "startTime": "07:00",
        "stopTime": "16:00",
        "chargeMode": 1,
        "maxChargePower": 11.0,
    },
    {
        "isValid": True,
        "isRepeat": True,
        "repeatPeriod": 31,
        "startTime": "17:00",
        "stopTime": "06:00",
        "chargeMode": 0,
        "maxChargePower": 11.0,
    },
]


class Response:
    def __init__(self, body=None, status=200):
        self.content = b"" if body is None else json.dumps(body).encode()
        self._body = body
        self.status_code = status

    def json(self):
        if self._body is None:
            raise ValueError("empty body")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    """Scripted session: answers by URL suffix and records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _answer(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response() if callable(response) else response
        raise AssertionError(f"unexpected request: {url}")

    def get(self, url, **kwargs):
        return self._answer("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, **kwargs)

    def writes(self, suffix):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith(suffix)]


class Client:
    _huawei_subdomain = "test"

    def __init__(self, routes):
        self._session = Session(routes)

    def keep_alive(self):
        pass


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    charger_api._DN_CACHE.clear()
    charger_api._HISTORY_CACHE.clear()
    charger_api._CONTROL_CACHE.clear()
    charger_api._WARNED.clear()
    charger_api._DN_CACHE["NE=1"] = ("301", "302")
    monkeypatch.setattr(charger_api, "_sleep", lambda seconds: None)


def test_finite_or_none():
    assert values.finite_or_none(1.5) == 1.5
    assert values.finite_or_none(-2.0) == -2.0
    assert values.finite_or_none(float("nan")) is None
    assert values.finite_or_none(float("inf")) is None


def test_plan_to_request_matches_what_the_app_sends():
    request = charger_api._plan_to_request(PLANS[1])
    assert request["calculatedStartTime"] == 1700
    assert request["calculatedStopTime"] == 600
    assert request["repeat"] is True and request["valid"] is True


def test_plan_to_request_rejects_malformed_times():
    with pytest.raises(ValueError):
        charger_api._plan_to_request({**PLANS[0], "startTime": "soon"})


def test_query_signals_reads_values():
    body = {"302": [{"id": 20001, "value": "11.0"}, {"id": 99, "value": "1"}]}
    client = Client({"get-config-info": Response(body)})
    assert charger_api._query_signals(client, "302", [20001]) == {20001: "11.0"}


def test_error_body_with_http_200_is_an_error():
    client = Client({"get-config-info": Response({"code": 5, "description": "denied"})})
    with pytest.raises(RuntimeError, match="denied"):
        charger_api._query_signals(client, "301", [20002])


def test_query_plan_fails_closed_without_switch_on():
    client = Client({"query-plan": Response({"plans": PLANS})})
    with pytest.raises(RuntimeError):
        charger_api._query_plan(client, "302")


def test_only_whitelisted_signals_can_be_written():
    client = Client({})
    for signal in (20006, 20007, 20012, 20014):
        with pytest.raises(ValueError):
            charger_api.set_charger_setting(client, "NE=1", signal, "1")
    assert client._session.calls == []


def test_values_are_validated_before_anything_is_sent():
    client = Client({})
    with pytest.raises(ValueError):
        charger_api.set_charger_setting(client, "NE=1", 20005, "7")
    assert client._session.calls == []


def test_power_limit_is_read_only():
    # Lowering it made the cloud drop the saved schedules on a real charger.
    client = Client({})
    with pytest.raises(ValueError):
        charger_api.set_charger_setting(client, "NE=1", 20001, "10.0")
    assert client._session.calls == []
    assert 20001 in charger_api.READONLY_SIGNALS


def test_settings_are_written_to_the_connector_dn():
    client = Client({"set-config-info": Response()})
    charger_api.set_charger_setting(client, "NE=1", 20002, "1")
    sent = client._session.writes("set-config-info")[0][2]["json"]
    assert sent == {"changeValues": [{"id": "20002", "value": "1"}], "dnId": 301}


def plan_client(*states, config_plan=None):
    """A client whose query-plan answers `states` in order, then repeats the last."""
    queue = list(states)

    def answer():
        body = queue.pop(0) if len(queue) > 1 else queue[0]
        return Response(body)

    return Client({"query-plan": answer, "config-plan": config_plan or Response()})


def test_schedule_write_resends_the_plans_and_changes_only_switch_on():
    client = plan_client({"switchOn": 1, "plans": PLANS})
    charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    writes = client._session.writes("config-plan")
    assert len(writes) == 1
    payload = writes[0][2]["json"]
    assert payload["switchOn"] == 0 and payload["dnId"] == 302
    assert [p["startTime"] for p in payload["plans"]] == ["07:00", "17:00"]


def test_schedule_write_is_skipped_when_already_in_that_state():
    client = plan_client({"switchOn": 0, "plans": PLANS})
    charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert client._session.writes("config-plan") == []


@pytest.mark.parametrize(
    "state, enabled",
    [
        ({"switchOn": 0, "plans": []}, True),
        ({"switchOn": 1, "plans": []}, False),
    ],
)
def test_an_empty_plan_list_is_never_written(state, enabled):
    client = plan_client(state)
    with pytest.raises(ValueError):
        charger_api.set_charger_schedule_enabled(client, "NE=1", enabled)
    assert client._session.writes("config-plan") == []


def test_a_reply_without_a_plan_list_is_never_written():
    client = plan_client({"switchOn": 1})
    with pytest.raises(RuntimeError, match="no plan list"):
        charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert client._session.writes("config-plan") == []


def test_plans_that_change_between_the_two_reads_are_never_written():
    client = plan_client(
        {"switchOn": 1, "plans": PLANS}, {"switchOn": 1, "plans": PLANS[:1]}
    )
    with pytest.raises(RuntimeError, match="between two reads"):
        charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert client._session.writes("config-plan") == []


def test_one_time_plans_are_never_resent():
    one_time = {**PLANS[0], "isRepeat": False, "startTime": "1790000000000"}
    client = plan_client({"switchOn": 1, "plans": [one_time]})
    with pytest.raises(ValueError, match="one-time"):
        charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert client._session.writes("config-plan") == []


def test_plans_with_missing_fields_are_never_resent():
    broken = {k: v for k, v in PLANS[0].items() if k != "maxChargePower"}
    client = plan_client({"switchOn": 1, "plans": [broken]})
    with pytest.raises(ValueError, match="maxChargePower"):
        charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert client._session.writes("config-plan") == []


def test_the_backup_is_taken_before_the_write_and_a_failing_backup_does_not_block():
    order = []
    client = plan_client({"switchOn": 1, "plans": PLANS})
    real_post = client._session.post

    def post(url, **kwargs):
        if url.endswith("config-plan"):
            order.append("write")
        return real_post(url, **kwargs)

    client._session.post = post
    charger_api.set_charger_schedule_enabled(
        client, "NE=1", False, backup=lambda dn, plans, on: order.append(("backup", on))
    )
    assert order == [("backup", True), "write"]

    client = plan_client({"switchOn": 1, "plans": PLANS})

    def failing(dn, plans, on):
        raise OSError("disk full")

    charger_api.set_charger_schedule_enabled(client, "NE=1", False, backup=failing)
    assert client._session.writes("config-plan")


def test_a_change_only_in_the_charge_power_is_detected():
    changed = [{**PLANS[0], "maxChargePower": 10.0}, PLANS[1]]
    assert charger_api._plan_signature(PLANS) != charger_api._plan_signature(changed)
    derived = [{**p, "calculatedStartTime": 1, "repeat": True} for p in PLANS]
    assert charger_api._plan_signature(PLANS) == charger_api._plan_signature(derived)


def test_plans_that_do_not_come_back_are_restored_once():
    damaged = {"switchOn": 0, "plans": PLANS[:1]}
    client = plan_client(
        {"switchOn": 1, "plans": PLANS},  # first read
        {"switchOn": 1, "plans": PLANS},  # second read
        damaged,
        damaged,
        damaged,  # the three checks after the write
        {"switchOn": 1, "plans": PLANS},  # the check after the restore
    )
    with pytest.raises(RuntimeError, match="were restored"):
        charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    writes = client._session.writes("config-plan")
    assert len(writes) == 2
    assert writes[0][2]["json"]["switchOn"] == 0
    assert writes[1][2]["json"]["switchOn"] == 1  # back to the previous state
    assert writes[1][2]["json"]["plans"] == writes[0][2]["json"]["plans"]


def test_a_failed_restore_is_reported_and_not_retried():
    damaged = {"switchOn": 0, "plans": PLANS[:1]}
    client = plan_client(
        {"switchOn": 1, "plans": PLANS}, {"switchOn": 1, "plans": PLANS}, damaged
    )
    with pytest.raises(RuntimeError, match="restoring failed"):
        charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert len(client._session.writes("config-plan")) == 2


def test_resending_the_real_plans_reproduces_the_apps_request():
    real = json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "real_plans.json").read_text()
    )
    for stored, sent_by_app in zip(
        real["query_plan_response"]["plans"], real["app_config_plan_request_plans"]
    ):
        assert charger_api._plan_to_request(stored) == sent_by_app


def test_a_failed_write_still_invalidates_the_control_cache():
    charger_api._CONTROL_CACHE["NE=1"] = (10**12, {"stale": True})
    client = Client({"set-config-info": Response(status=500)})
    with pytest.raises(RuntimeError):
        charger_api.set_charger_setting(client, "NE=1", 20002, "1")
    assert "NE=1" not in charger_api._CONTROL_CACHE


def test_history_reads_the_newest_record_and_survives_failures():
    body = {
        "code": 0,
        "data": {"total": 174, "records": [{"totalPower": 40.1, "chargeMode": 0}]},
    }
    client = Client({"list-charge-record": Response(body)})
    history = charger_api._query_charge_history(client, "302", "Europe/Berlin")
    assert history["total"] == 174 and history["last"]["totalPower"] == 40.1
    sent = client._session.calls[0][2]["json"]
    assert sent["timeZoneId"] == "Europe/Berlin"

    charger_api._HISTORY_CACHE.clear()
    failing = Client({"list-charge-record": Response({"code": 3, "description": "no"})})
    assert charger_api._query_charge_history(failing, "302") == {
        "total": None,
        "last": None,
    }
    # the failure is cached briefly, so the next poll does not ask again
    assert charger_api._query_charge_history(failing, "302")["total"] is None
    assert len(failing._session.calls) == 1


def test_normalize_turns_nan_into_none():
    raw = {"302": [{"id": 1, "realValue": "NaN"}, {"id": 2, "realValue": "-1.5"}]}
    out = charger_api._normalize_charger_payload(raw)["value_map"]
    assert out[("302", 1)] is None
    assert out[("302", 2)] == -1.5


def dn_client(children, dn_id):
    return Client(
        {
            "organization/v1/tree": Response({"childList": children}),
            "mo-details": Response({"data": {"mo": {"dnId": dn_id}}}),
        }
    )


def test_dn_ids_are_looked_up_once_and_cached():
    client = dn_client([{"elementId": 301}], 302)
    assert charger_api._get_dn_ids(client, "NE=9") == ("301", "302")
    assert charger_api._get_dn_ids(client, "NE=9") == ("301", "302")
    assert len(client._session.calls) == 2


@pytest.mark.parametrize(
    "children, dn_id",
    [
        ([], 302),
        ([{"nope": 1}], 302),
        ([{"elementId": "abc"}], 302),
        ([{"elementId": 301}], None),
    ],
)
def test_unusable_dn_ids_raise_and_are_not_cached(children, dn_id):
    client = dn_client(children, dn_id)
    with pytest.raises(RuntimeError):
        charger_api._get_dn_ids(client, "NE=9")
    assert "NE=9" not in charger_api._DN_CACHE


def test_more_than_one_connector_uses_the_first_and_warns_once():
    client = dn_client([{"elementId": 301}, {"elementId": 305}], 302)
    assert charger_api._get_dn_ids(client, "NE=9") == ("301", "302")
    assert "connectors:NE=9" in charger_api._WARNED


def test_a_signal_is_written_to_the_dn_the_whitelist_names(monkeypatch):
    monkeypatch.setitem(charger_api.WRITABLE_SIGNALS, 99999, charger_api.CHARGER)
    client = Client({"set-config-info": Response()})
    charger_api.set_charger_setting(client, "NE=1", 99999, "1")
    assert client._session.writes("set-config-info")[0][2]["json"]["dnId"] == 302


def realtime_client():
    return Client(
        {
            "get-realtime-info": Response({"301": [{"id": 1, "realValue": "5"}]}),
            "list-charge-record": Response(
                {"code": 0, "data": {"total": 0, "records": []}}
            ),
            "get-config-info": Response(
                {
                    "301": [{"id": 20002, "value": "0"}],
                    "302": [{"id": 20001, "value": "11.0"}],
                }
            ),
            "query-plan": Response({"switchOn": 0, "plans": PLANS}),
        }
    )


def test_control_is_only_read_when_charger_control_is_on():
    client = realtime_client()
    data = charger_api.get_charger_data(client, "NE=1", "UTC")
    assert data["control"] is None
    called = [c[1].rsplit("/", 1)[-1] for c in client._session.calls]
    assert "get-config-info" not in called and "query-plan" not in called

    charger_api._HISTORY_CACHE.clear()
    client = realtime_client()
    data = charger_api.get_charger_data(client, "NE=1", "UTC", include_control=True)
    assert data["control"]["schedule_on"] is False
    assert data["control"]["settings"][20002] == "0"
    assert data["control"]["settings"][20001] == "11.0"


def test_a_failing_control_read_does_not_take_the_sensors_down():
    client = realtime_client()
    client._session.routes["get-config-info"] = Response(status=500)
    data = charger_api.get_charger_data(client, "NE=1", "UTC", include_control=True)
    assert data["control"] is None and data["value_map"]


def test_clear_caches_forgets_one_charger():
    charger_api._CONTROL_CACHE["NE=1"] = (1, {})
    charger_api._WARNED.add("control:NE=1")
    charger_api.clear_caches("NE=1")
    assert "NE=1" not in charger_api._DN_CACHE
    assert "NE=1" not in charger_api._CONTROL_CACHE
    assert "control:NE=1" not in charger_api._WARNED
