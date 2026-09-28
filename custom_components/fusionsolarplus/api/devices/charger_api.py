"""Charger API helpers."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

_LOGGER = logging.getLogger(__name__)

CONNECTOR = "connector"
CHARGER = "charger"

WORKING_MODE_SIGNAL_ID = 20002  # 0 = Normal charge, 1 = PV Power Preferred

# Read-only values shown as diagnostic sensors (never written).
READONLY_SIGNALS: dict[int, str] = {
    20006: CONNECTOR,  # Max Charging Power from Grid
    20007: CONNECTOR,  # Surplus Power to Start Charging
}

# Only these signals may ever be written. Which dn they live on was taken
# from the app's own requests: the working mode and PV settings belong to the
# connector (tree child), the power limit to the charger device itself.
WRITABLE_SIGNALS: dict[int, str] = {
    20002: CONNECTOR,  # Working Mode
    20005: CONNECTOR,  # Control Charging Connector Lock
    538976529: CONNECTOR,  # Dynamic Charge Power
    20001: CHARGER,  # Charge Power Upper Limit
}

_DN_CACHE: dict[str, tuple[str, str]] = {}
_HISTORY_CACHE: dict[str, tuple[float, dict]] = {}
HISTORY_TTL_SECONDS = 300
HISTORY_WINDOW_DAYS = 180


def _base_url(client: Any) -> str:
    return f"https://{client._huawei_subdomain}.fusionsolar.huawei.com"


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
    r.raise_for_status()
    return r.json()


def _query_signals(
    client: Any, dn_id: str, signal_ids: list[int]
) -> tuple[dict[int, str], dict[int, tuple[float, float]]]:
    """Read config signals; returns ({id: value}, {id: (min, max)}).

    The ranges are what the cloud allows for this installation, e.g. the
    charge power limit tops out at 11 kW unless the site is approved for more.
    """
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/device/get-config-info"
    payload = {
        "conditions": [{"dnId": int(dn_id), "queryAll": False, "signals": signal_ids}],
        "verbose": True,
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()
    values: dict[int, str] = {}
    ranges: dict[int, tuple[float, float]] = {}
    for signals in r.json().values():
        if not isinstance(signals, list):
            continue
        for signal in signals:
            if signal.get("id") in signal_ids and signal.get("value") is not None:
                signal_id = int(signal["id"])
                values[signal_id] = str(signal["value"])
                limits = signal.get("ranges") or []
                if limits:
                    ranges[signal_id] = (
                        float(limits[0]["minValue"]),
                        float(limits[0]["maxValue"]),
                    )
    return values, ranges


def _query_charge_history(client: Any, charger_dn_id: str) -> dict:
    """Latest charge session and total count, cached for a few minutes."""
    cached = _HISTORY_CACHE.get(charger_dn_id)
    if cached and time.time() - cached[0] < HISTORY_TTL_SECONDS:
        return cached[1]

    # The app only ever asks for about half a year at a time (Apr 1 - Sep 30),
    # so stay inside that window instead of asking for years.
    now = int(time.time())
    tz = datetime.now().astimezone().tzinfo
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v2/charger/list-charge-record"
    payload = {
        "timeZoneId": getattr(tz, "key", None) or "UTC",
        "pageNo": 1,
        "pageSize": 20,
        "dnId": int(charger_dn_id),
        "startTime": str(now - HISTORY_WINDOW_DAYS * 86400),
        "endTime": str(now),
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()
    body = r.json()
    # The cloud answers HTTP 200 with an error in the body when it dislikes a request.
    if str(body.get("code", "0")) != "0":
        raise RuntimeError(f"list-charge-record: {body.get('description') or body}")
    data = body.get("data") or {}
    records = data.get("records") or []
    history = {"total": data.get("total"), "last": records[0] if records else None}
    _HISTORY_CACHE[charger_dn_id] = (time.time(), history)
    return history


def get_charger_data(client: Any, device_dn: str | None = None) -> dict:
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
        connector_signals = [
            s for s, dn in {**WRITABLE_SIGNALS, **READONLY_SIGNALS}.items() if dn == CONNECTOR
        ]
        charger_signals = [s for s, dn in WRITABLE_SIGNALS.items() if dn == CHARGER]
        settings, ranges = _query_signals(client, dn_id_1, connector_signals)
        charger_settings, charger_ranges = _query_signals(client, dn_id_2, charger_signals)
        settings.update(charger_settings)
        ranges.update(charger_ranges)
        data["control"] = {
            "ranges": ranges,
            "working_mode": settings.get(WORKING_MODE_SIGNAL_ID),
            "schedule_on": bool(_query_plan(client, dn_id_2).get("switchOn")),
            "settings": settings,
        }
    except Exception as err:
        _LOGGER.warning("Could not read charger control state: %r", err)
        data["control"] = None

    try:
        data["history"] = _query_charge_history(client, dn_id_2)
    except Exception as err:
        _LOGGER.warning("Could not read charge history: %r", err)
        data["history"] = None
    return data


def set_charger_setting(client: Any, device_dn: str, signal_id: int, value: str) -> None:
    """Write one whitelisted config signal to the dn the app writes it to."""
    if signal_id not in WRITABLE_SIGNALS:
        raise ValueError(f"Signal {signal_id} is not writable through this integration")
    client.keep_alive()
    connector_dn_id, charger_dn_id = _get_dn_ids(client, device_dn)
    dn_id = connector_dn_id if WRITABLE_SIGNALS[signal_id] == CONNECTOR else charger_dn_id
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/device/set-config-info"
    payload = {
        "changeValues": [{"id": str(signal_id), "value": str(value)}],
        "dnId": int(dn_id),
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()


def set_charger_working_mode(client: Any, device_dn: str, value: str) -> None:
    """Set the working mode: "0" = Normal charge, "1" = PV Power Preferred."""
    set_charger_setting(client, device_dn, WORKING_MODE_SIGNAL_ID, value)


def _plan_to_request(plan: dict) -> dict:
    """Rebuild a plan the way the app sends it (adds the calculated* fields)."""
    start, stop = plan["startTime"], plan["stopTime"]
    if plan.get("isRepeat"):
        calc_start = int(start.replace(":", ""))
        calc_stop = int(stop.replace(":", ""))
    else:
        calc_start = int(start) // 1000
        calc_stop = int(stop) // 1000
    return {
        **plan,
        "calculatedStartTime": calc_start,
        "calculatedStopTime": calc_stop,
        "repeat": plan.get("isRepeat"),
        "valid": plan.get("isValid"),
    }


def set_charger_schedule_enabled(client: Any, device_dn: str, enabled: bool) -> None:
    """Switch the charging schedule on/off, resending the existing plans unchanged.

    config-plan replaces the whole plan list, so the current plans are read
    first and sent back as they are - only `switchOn` changes.
    """
    client.keep_alive()
    _, charger_dn_id = _get_dn_ids(client, device_dn)
    current = _query_plan(client, charger_dn_id)
    if not current.get("plans"):
        raise ValueError(
            "No charging plans returned - refusing to write, config-plan would erase them"
        )
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/charger/plan/config-plan"
    payload = {
        "plans": [_plan_to_request(p) for p in current["plans"]],
        "switchOn": 1 if enabled else 0,
        "accountId": "",
        "dnId": int(charger_dn_id),
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()


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
                value_map[(signal_type_id, int(signal_id))] = float(raw_value)
            except (TypeError, ValueError):
                value_map[(signal_type_id, int(signal_id))] = raw_value
    return {"raw_data": raw_data, "value_map": value_map}
