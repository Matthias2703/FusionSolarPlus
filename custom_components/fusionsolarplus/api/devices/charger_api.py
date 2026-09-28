"""Charger API helpers."""

from __future__ import annotations

import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)


WORKING_MODE_SIGNAL_ID = 20002  # 0 = Normal charge, 1 = PV Power Preferred


def _base_url(client: Any) -> str:
    return f"https://{client._huawei_subdomain}.fusionsolar.huawei.com"


def _get_dn_ids(client: Any, device_dn: str | None) -> tuple[str, str]:
    """Return (connector_dn_id, charger_dn_id) for the charger device."""
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

    return connector_dn_id, charger_dn_id


def _query_plan(client: Any, connector_dn_id: str) -> dict:
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/charger/plan/query-plan"
    r = client._session.get(url=url, params={"dnId": int(connector_dn_id)})
    r.raise_for_status()
    return r.json()


def _query_working_mode(client: Any, charger_dn_id: str) -> str | None:
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/device/get-config-info"
    payload = {
        "conditions": [
            {
                "dnId": int(charger_dn_id),
                "queryAll": False,
                "signals": [WORKING_MODE_SIGNAL_ID],
            }
        ],
        "verbose": True,
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()
    for signals in r.json().values():
        if not isinstance(signals, list):
            continue
        for signal in signals:
            if signal.get("id") == WORKING_MODE_SIGNAL_ID:
                return str(signal.get("value"))
    return None


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

    # Control state (working mode + schedule) is best-effort: a failure here
    # must not take the read-only sensors down with it.
    try:
        data["control"] = {
            "working_mode": _query_working_mode(client, dn_id_2),
            "schedule_on": bool(_query_plan(client, dn_id_1).get("switchOn")),
        }
    except Exception as err:
        _LOGGER.warning("Could not read charger control state: %r", err)
        data["control"] = None
    return data


def set_charger_working_mode(client: Any, device_dn: str, value: str) -> None:
    """Set the working mode: "0" = Normal charge, "1" = PV Power Preferred."""
    client.keep_alive()
    _, charger_dn_id = _get_dn_ids(client, device_dn)
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/device/set-config-info"
    payload = {
        "changeValues": [{"id": str(WORKING_MODE_SIGNAL_ID), "value": value}],
        "dnId": int(charger_dn_id),
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()


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
    connector_dn_id, _ = _get_dn_ids(client, device_dn)
    current = _query_plan(client, connector_dn_id)
    url = f"{_base_url(client)}/rest/neteco/web/homemgr/v1/charger/plan/config-plan"
    payload = {
        "plans": [_plan_to_request(p) for p in current.get("plans", [])],
        "switchOn": 1 if enabled else 0,
        "accountId": "",
        "dnId": int(connector_dn_id),
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
