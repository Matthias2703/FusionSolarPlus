"""Charger API helpers."""

from __future__ import annotations

import time
from typing import Any


def get_charger_data(client: Any, device_dn: str | None = None) -> dict:
    client.keep_alive()

    url = f"https://{client._huawei_subdomain}.fusionsolar.huawei.com/rest/dp/pvms/organization/v1/tree"
    payload = {
        "parentDn": device_dn,
        "treeDepth": "device",
        "pageParam": {"needPage": True},
        "filterCond": {"nameType": "device", "mocIdInclude": [60081]},
        "displayCond": {"self": False, "status": True},
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()
    response = r.json()
    dn_id_1 = response["childList"][0]["elementId"]

    url = f"https://{client._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/device/v1/mo-details"
    params = (("dn", device_dn), ("_", round(time.time() * 1000)))
    r = client._session.get(url=url, params=params)
    r.raise_for_status()
    response = r.json()
    dn_id_2 = str(response.get("data", {}).get("mo", {}).get("dnId"))

    url = f"https://{client._huawei_subdomain}.fusionsolar.huawei.com/rest/neteco/web/homemgr/v1/device/get-realtime-info"
    payload = {
        "conditions": [
            {"dnId": dn_id_1, "queryAll": True},
            {"dnId": dn_id_2, "queryAll": True},
        ]
    }
    r = client._session.post(url=url, json=payload)
    r.raise_for_status()
    return _normalize_charger_payload(r.json())


def get_charging_pile_signal_value(raw_data: dict, signal_id: int) -> Any:
    """Look up one raw signal value from the charging-pile (connector) signal list.

    `raw_data` is keyed by dnId, not by a fixed moc id, so the charging-pile
    list has to be identified by its contents (same approach as
    devices/charger/sensor.py's _get_signal_list_for_type) rather than by key.
    """
    for signals_list in raw_data.values():
        if not isinstance(signals_list, list):
            continue
        names = {s.get("name") for s in signals_list if s.get("name")}
        if "Charging Connector No." not in names:
            continue
        for signal in signals_list:
            if signal.get("id") == signal_id:
                return signal.get("realValue", signal.get("value"))
    return None


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
