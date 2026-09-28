"""Tests for the charger API layer.

These run without Home Assistant: the package __init__ files are stubbed so
only api/values.py and api/devices/charger_api.py are imported. Response
bodies mirror what the FusionSolar app receives.
"""

import importlib
import json
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components"
for name, path in [
    ("custom_components", ROOT),
    ("custom_components.fusionsolarplus", ROOT / "fusionsolarplus"),
    ("custom_components.fusionsolarplus.api", ROOT / "fusionsolarplus" / "api"),
    (
        "custom_components.fusionsolarplus.api.devices",
        ROOT / "fusionsolarplus" / "api" / "devices",
    ),
]:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules.setdefault(name, module)

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
def fresh_state():
    charger_api._DN_CACHE.clear()
    charger_api._HISTORY_CACHE.clear()
    charger_api._CONTROL_CACHE.clear()
    charger_api._WARNED.clear()
    charger_api._DN_CACHE["NE=1"] = ("301", "302")


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
    client = Client(
        {"get-config-info": Response({"code": 5, "description": "denied"})}
    )
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


def test_schedule_write_resends_the_plans_and_changes_only_switch_on():
    state = {"switchOn": 1, "plans": PLANS}
    client = Client(
        {
            "query-plan": lambda: Response(state),
            "config-plan": Response(),
        }
    )
    charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    payload = client._session.writes("config-plan")[0][2]["json"]
    assert payload["switchOn"] == 0 and payload["dnId"] == 302
    assert [p["startTime"] for p in payload["plans"]] == ["07:00", "17:00"]


def test_schedule_write_is_skipped_when_already_in_that_state():
    client = Client({"query-plan": Response({"switchOn": 0, "plans": PLANS})})
    charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert client._session.writes("config-plan") == []


def test_empty_plans_are_never_enabled_but_can_be_switched_off():
    client = Client({"query-plan": Response({"switchOn": 0, "plans": []})})
    with pytest.raises(ValueError):
        charger_api.set_charger_schedule_enabled(client, "NE=1", True)
    client = Client(
        {"query-plan": Response({"switchOn": 1, "plans": []}), "config-plan": Response()}
    )
    charger_api.set_charger_schedule_enabled(client, "NE=1", False)
    assert client._session.writes("config-plan")


def test_schedule_write_reports_plans_that_changed_underneath():
    answers = iter(
        [
            Response({"switchOn": 1, "plans": PLANS}),
            Response({"switchOn": 0, "plans": PLANS[:1]}),
        ]
    )
    client = Client({"query-plan": lambda: next(answers), "config-plan": Response()})
    with pytest.raises(RuntimeError, match="differ"):
        charger_api.set_charger_schedule_enabled(client, "NE=1", False)


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
