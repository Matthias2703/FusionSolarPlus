"""Charger API helpers."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

from ..values import finite_or_none

_LOGGER = logging.getLogger(__name__)

CONNECTOR = "connector"
CHARGER = "charger"

WORKING_MODE_SIGNAL_ID = 20002  # 0 = Normal charge, 1 = PV Power Preferred

# Only these signals may ever be written. Which dn they live on was taken
# from the app's own requests: they all belong to the connector (tree child).
WRITABLE_SIGNALS: dict[int, str] = {
    20002: CONNECTOR,  # Working Mode
    20005: CONNECTOR,  # Control Charging Connector Lock
    538976529: CONNECTOR,  # Dynamic Charge Power
}

# Read-only values shown as diagnostic sensors (never written). The power limit
# is read-only on purpose: lowering it below the power of a saved schedule made
# the cloud drop the user's schedules (seen on a real SCharger).
READONLY_SIGNALS: dict[int, str] = {
    20001: CHARGER,  # Charge Power Upper Limit
    20006: CONNECTOR,  # Max Charging Power from Grid
    20007: CONNECTOR,  # Surplus Power to Start Charging
}

# Values the cloud accepts for the enum-like signals.
ENUM_VALUES: dict[int, set[str]] = {
    20002: {"0", "1"},
    20005: {"0", "1", "2"},
    538976529: {"0", "1"},
}

HISTORY_TTL_SECONDS = 300
HISTORY_RETRY_SECONDS = 60
HISTORY_WINDOW_DAYS = 180
CONTROL_TTL_SECONDS = 45

# Plan handling: the plan list is replaced as a whole by config-plan, so it is
# read twice before and re-checked after every write.
PLAN_READ_PAUSE = 1.0
PLAN_VERIFY_CHECKS = 3
PLAN_VERIFY_PAUSE = 3.0
PLAN_REQUIRED_FIELDS = (
    "startTime",
    "stopTime",
    "chargeMode",
    "repeatPeriod",
    "maxChargePower",
    "isValid",
    "isRepeat",
)
PLAN_DERIVED_FIELDS = ("calculatedStartTime", "calculatedStopTime", "repeat", "valid")

_DN_CACHE: dict[str, tuple[str, str]] = {}
_HISTORY_CACHE: dict[str, tuple[float, dict]] = {}
_CONTROL_CACHE: dict[str, tuple[float, dict]] = {}
_WARNED: set[str] = set()
_sleep = time.sleep
_LOCK_GUARD = threading.Lock()


def _client_lock(client: Any) -> threading.RLock:
    """One lock per client: polling and writes share a single requests session."""
    with _LOCK_GUARD:
        lock = getattr(client, "_charger_lock", None)
        if lock is None:
            lock = threading.RLock()
            client._charger_lock = lock
        return lock


def _warn_once(key: str, message: str, err: Exception) -> None:
    """Log a recurring failure once until it recovers, not on every poll."""
    if key not in _WARNED:
        _WARNED.add(key)
        _LOGGER.warning("%s: %r", message, err)


def _recovered(key: str) -> None:
    _WARNED.discard(key)


def invalidate_control_cache(device_dn: str | None) -> None:
    _CONTROL_CACHE.pop(device_dn, None)


def _base_url(client: Any) -> str:
    return f"https://{client._huawei_subdomain}.fusionsolar.huawei.com"


def _json(r: Any) -> Any:
    """Return the parsed body, raising on HTTP errors and on error bodies.

    The cloud sometimes answers HTTP 200 with the failure inside the body, and
    successful writes return an empty body.
    """
    r.raise_for_status()
    if not r.content:
        return None
    try:
        body = r.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        if "exceptionId" in body:
            raise RuntimeError(
                f"cloud error {body['exceptionId']}: {body.get('descArgs') or body}"
            )
        if "code" in body and str(body["code"]) != "0":
            raise RuntimeError(
                f"cloud error code {body['code']}: {body.get('description')}"
            )
    return body


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


def _get_dn_ids(client: Any, device_dn: str | None) -> tuple[str, str]:
    """Return (connector_dn_id, charger_dn_id).

    connector = child of the charger in the device tree (holds the working
    mode signal); charger = the device itself (holds the schedule).
    The ids never change for a device, so they are looked up once.
    """
    if device_dn in _DN_CACHE:
        return _DN_CACHE[device_dn]

    url = f"{_base_url(client)}/rest/dp/pvms/organization/v1/tree"
    payload = {
        "parentDn": device_dn,
        "treeDepth": "device",
        "pageParam": {"needPage": True},
        "filterCond": {"nameType": "device", "mocIdInclude": [60081]},
        "displayCond": {"self": False, "status": True},
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()
    connector_dn_id = r.json()["childList"][0]["elementId"]

    url = f"{_base_url(client)}/rest/pvms/web/device/v1/mo-details"
    params = (("dn", device_dn), ("_", round(time.time() * 1000)))
    r = client._session.get(url=url, params=params)
    r.raise_for_status()
    charger_dn_id = str(r.json().get("data", {}).get("mo", {}).get("dnId"))

    _DN_CACHE[device_dn] = (str(connector_dn_id), charger_dn_id)
    return _DN_CACHE[device_dn]


def _query_plan(client: Any, charger_dn_id: str) -> dict:
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/charger/plan/query-plan"
    r = client._session.get(url=url, params={"dnId": int(charger_dn_id)})
    body = _json(r)
    if not isinstance(body, dict) or "switchOn" not in body:
        # Fail closed: a missing switchOn must not read as "schedule off".
        raise RuntimeError(f"query-plan returned no switchOn: {body!r}")
    return body


def _query_signals(client: Any, dn_id: str, signal_ids: list[int]) -> dict[int, str]:
    """Read config signals; returns {id: value}."""
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/device/get-config-info"
    payload = {
        "conditions": [{"dnId": int(dn_id), "queryAll": False, "signals": signal_ids}],
        "verbose": True,
    }
    body = _json(client._session.post(url=url, json=payload))
    values: dict[int, str] = {}
    for signals in (body or {}).values():
        if not isinstance(signals, list):
            continue
        for signal in signals:
            try:
                signal_id = int(signal.get("id"))
            except (TypeError, ValueError):
                continue
            if signal_id in signal_ids and signal.get("value") is not None:
                values[signal_id] = str(signal["value"])
    return values


def _read_control(client: Any, device_dn: str | None, dn_1: str, dn_2: str) -> dict:
    """Working mode, settings and schedule state; cached for CONTROL_TTL_SECONDS."""
    cached = _CONTROL_CACHE.get(device_dn)
    if cached and time.time() - cached[0] < CONTROL_TTL_SECONDS:
        return cached[1]

    all_signals = {**WRITABLE_SIGNALS, **READONLY_SIGNALS}
    connector_signals = [s for s, dn in all_signals.items() if dn == CONNECTOR]
    charger_signals = [s for s, dn in all_signals.items() if dn == CHARGER]
    settings = _query_signals(client, dn_1, connector_signals)
    settings.update(_query_signals(client, dn_2, charger_signals))
    control = {
        "working_mode": settings.get(WORKING_MODE_SIGNAL_ID),
        "schedule_on": _truthy(_query_plan(client, dn_2)["switchOn"]),
        "settings": settings,
    }
    _CONTROL_CACHE[device_dn] = (time.time(), control)
    return control


def _query_charge_history(
    client: Any, charger_dn_id: str, time_zone: str = "UTC"
) -> dict:
    """Latest charge session and session count, cached for a few minutes."""
    cached = _HISTORY_CACHE.get(charger_dn_id)
    if cached and time.time() - cached[0] < HISTORY_TTL_SECONDS:
        return cached[1]

    # The app only ever asks for about half a year at a time (Apr 1 - Sep 30),
    # so stay inside that window instead of asking for years.
    now = int(time.time())
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v2/charger/list-charge-record"
    payload = {
        "timeZoneId": time_zone,
        "pageNo": 1,
        "pageSize": 20,
        "dnId": int(charger_dn_id),
        "startTime": str(now - HISTORY_WINDOW_DAYS * 86400),
        "endTime": str(now),
    }
    try:
        body = _json(client._session.post(url=url, json=payload)) or {}
        data = body.get("data") or {}
        records = data.get("records") or []
        try:
            total = int(data.get("total"))
        except (TypeError, ValueError):
            total = None
        history = {"total": total, "last": records[0] if records else None}
    except Exception as err:
        # Retry sooner than the normal TTL, but not on every poll.
        previous = cached[1] if cached else {"total": None, "last": None}
        _HISTORY_CACHE[charger_dn_id] = (
            time.time() - HISTORY_TTL_SECONDS + HISTORY_RETRY_SECONDS,
            previous,
        )
        _warn_once(f"history:{charger_dn_id}", "Could not read charge history", err)
        return previous
    _recovered(f"history:{charger_dn_id}")
    _HISTORY_CACHE[charger_dn_id] = (time.time(), history)
    return history


def get_charger_data(
    client: Any, device_dn: str | None = None, time_zone: str = "UTC"
) -> dict:
    with _client_lock(client):
        client.keep_alive()

        dn_id_1, dn_id_2 = _get_dn_ids(client, device_dn)

        url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/device/get-realtime-info"
        payload = {
            "conditions": [
                {"dnId": dn_id_1, "queryAll": True},
                {"dnId": dn_id_2, "queryAll": True},
            ]
        }
        r = client._session.post(url=url, json=payload)
        r.raise_for_status()
        data = _normalize_charger_payload(r.json())

        # Control state and history are best-effort: a failure here must not
        # take the read-only sensors down with it.
        try:
            data["control"] = _read_control(client, device_dn, dn_id_1, dn_id_2)
            _recovered(f"control:{device_dn}")
        except Exception as err:
            _warn_once(
                f"control:{device_dn}", "Could not read charger control state", err
            )
            data["control"] = None

        data["history"] = _query_charge_history(client, dn_id_2, time_zone)
        return data


def _validate(signal_id: int, value: str) -> None:
    if signal_id in ENUM_VALUES and str(value) not in ENUM_VALUES[signal_id]:
        raise ValueError(f"{value!r} is not a valid value for signal {signal_id}")


def set_charger_setting(
    client: Any, device_dn: str, signal_id: int, value: str
) -> None:
    """Write one whitelisted, validated config signal to the connector dn."""
    if signal_id not in WRITABLE_SIGNALS:
        raise ValueError(f"Signal {signal_id} is not writable through this integration")
    _validate(signal_id, value)
    with _client_lock(client):
        client.keep_alive()
        dn_id, _ = _get_dn_ids(client, device_dn)
        url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/device/set-config-info"
        payload = {
            "changeValues": [{"id": str(signal_id), "value": str(value)}],
            "dnId": int(dn_id),
        }
        try:
            _json(client._session.post(url=url, json=payload))
        finally:
            invalidate_control_cache(device_dn)


def set_charger_working_mode(client: Any, device_dn: str, value: str) -> None:
    """Set the working mode: "0" = Normal charge, "1" = PV Power Preferred."""
    set_charger_setting(client, device_dn, WORKING_MODE_SIGNAL_ID, value)


def _hhmm(value: str) -> int:
    return int(datetime.strptime(value[:5], "%H:%M").strftime("%H%M"))


def _plan_to_request(plan: dict) -> dict:
    """Rebuild a repeating plan the way the app sends it (adds the derived fields)."""
    return {
        **plan,
        "calculatedStartTime": _hhmm(plan["startTime"]),
        "calculatedStopTime": _hhmm(plan["stopTime"]),
        "repeat": plan.get("isRepeat"),
        "valid": plan.get("isValid"),
    }


def _plan_signature(plans: list[dict] | None) -> list[str]:
    """Every field the cloud stores, except the ones derived from them."""
    return sorted(
        json.dumps(
            {k: v for k, v in p.items() if k not in PLAN_DERIVED_FIELDS},
            sort_keys=True,
        )
        for p in plans or []
    )


def _check_plans_can_be_resent(plans: list[dict]) -> None:
    """Refuse plans we cannot reproduce exactly (one-time plans, missing fields)."""
    if not plans:
        raise ValueError(
            "No charging plans found - refusing to switch a schedule that has none"
        )
    for plan in plans:
        missing = [f for f in PLAN_REQUIRED_FIELDS if f not in plan]
        if missing:
            raise ValueError(f"Charging plan lacks {missing}; change the mode in the app")
        if not plan["isRepeat"]:
            raise ValueError(
                "A one-time charging plan exists; change the mode in the app instead"
            )


def _read_plans_stable(client: Any, charger_dn_id: str, first: dict) -> dict:
    """Read the plans a second time and insist both reads agree and are complete."""
    _sleep(PLAN_READ_PAUSE)
    second = _query_plan(client, charger_dn_id)
    for body in (first, second):
        if not isinstance(body.get("plans"), list):
            raise RuntimeError("query-plan returned no plan list - not touching the plans")
    if _truthy(first["switchOn"]) != _truthy(second["switchOn"]) or _plan_signature(
        first["plans"]
    ) != _plan_signature(second["plans"]):
        raise RuntimeError("Charging plans changed between two reads - not touching them")
    return second


def _plans_match(client: Any, charger_dn_id: str, expected: list[dict]) -> bool:
    """True once the cloud reports exactly `expected`; retries while it settles."""
    for _ in range(PLAN_VERIFY_CHECKS):
        _sleep(PLAN_VERIFY_PAUSE)
        try:
            after = _query_plan(client, charger_dn_id)
        except Exception as err:
            _LOGGER.warning("Could not re-read the charging plans: %r", err)
            continue
        if _plan_signature(after.get("plans")) == _plan_signature(expected):
            return True
    return False


def _write_plans(client: Any, charger_dn_id: str, plans: list[dict], on: bool) -> None:
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/charger/plan/config-plan"
    payload = {
        "plans": [_plan_to_request(p) for p in plans],
        "switchOn": 1 if on else 0,
        "accountId": "",
        "dnId": int(charger_dn_id),
    }
    _json(client._session.post(url=url, json=payload))


def set_charger_schedule_enabled(
    client: Any,
    device_dn: str,
    enabled: bool,
    backup: Callable[[str, list[dict], bool], None] | None = None,
) -> None:
    """Switch the charging schedule on/off, resending the existing plans unchanged.

    config-plan replaces the whole plan list, so nothing is written unless two
    reads agree on a complete list of repeating plans. The plans are logged
    (WARNING) and handed to `backup` first, sent back as they are (only
    `switchOn` changes) and compared field by field afterwards; if they do not
    come back, one restore attempt is made. Nothing is written if the schedule
    is already in the requested state.
    """
    with _client_lock(client):
        client.keep_alive()
        _, charger_dn_id = _get_dn_ids(client, device_dn)
        first = _query_plan(client, charger_dn_id)
        if _truthy(first["switchOn"]) == enabled:
            return

        current = _read_plans_stable(client, charger_dn_id, first)
        plans = current["plans"]
        was_on = _truthy(current["switchOn"])
        _check_plans_can_be_resent(plans)

        _LOGGER.warning(
            "Charging plans before switching the schedule %s (kept as a backup): %s",
            "on" if enabled else "off",
            json.dumps(plans),
        )
        if backup is not None:
            try:
                backup(device_dn, plans, was_on)
            except Exception as err:
                _LOGGER.error("Could not store the charging plan backup: %r", err)

        try:
            _write_plans(client, charger_dn_id, plans, enabled)
        finally:
            invalidate_control_cache(device_dn)
        if _plans_match(client, charger_dn_id, plans):
            return

        _LOGGER.error("Charging plans differ after the write, restoring the previous plans")
        try:
            _write_plans(client, charger_dn_id, plans, was_on)
            restored = _plans_match(client, charger_dn_id, plans)
        except Exception as err:
            _LOGGER.error("Restoring the charging plans failed: %r", err)
            restored = False
        finally:
            invalidate_control_cache(device_dn)
        raise RuntimeError(
            "Charging plans differ after the write; "
            + (
                "the previous plans were restored"
                if restored
                else "restoring failed, check the plans in the FusionSolar app "
                "(the previous plans are in the log and the plan backup)"
            )
        )


def _normalize_charger_payload(raw_data: dict) -> dict:
    value_map: dict[tuple[str, int], Any] = {}
    for signal_type_id, signals_list in raw_data.items():
        if not isinstance(signals_list, list):
            continue
        for signal in signals_list:
            signal_id = signal.get("id")
            if signal_id is None:
                continue
            raw_value = signal.get("realValue", signal.get("value"))
            if raw_value in (None, "-", "N/A", "n/a"):
                value_map[(signal_type_id, int(signal_id))] = None
                continue
            try:
                value_map[(signal_type_id, int(signal_id))] = finite_or_none(
                    float(raw_value)
                )
            except (TypeError, ValueError):
                value_map[(signal_type_id, int(signal_id))] = raw_value
    return {"raw_data": raw_data, "value_map": value_map}
