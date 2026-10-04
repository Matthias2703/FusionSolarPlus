"""Which charger entities are no longer wanted (no Home Assistant imports)."""

# Entities that only exist while charger control is switched on.
CONTROL_SUFFIXES = (
    "_charging_mode_select",
    "_connector_lock_control",
    "_dynamic_charge_power",
    "_start_charging",
    "_stop_charging",
    "_charge_power_limit_sensor",
    "_pv_start_surplus_sensor",
    "_pv_max_grid_power_sensor",
)

# The power limit used to be a writable number entity; it is a sensor now.
LEGACY_NUMBER_SUFFIX = "_charge_power_limit"


def stale_entity_ids(entities, device_id: str, control_on: bool) -> list[str]:
    """Entity ids of a charger entry that should be removed from the registry."""
    stale = []
    for entity in entities:
        unique_id = entity.unique_id or ""
        if (
            entity.domain == "number"
            and unique_id == f"{device_id}{LEGACY_NUMBER_SUFFIX}"
        ):
            stale.append(entity.entity_id)
        elif not control_on and any(
            unique_id == f"{device_id}{suffix}" for suffix in CONTROL_SUFFIXES
        ):
            stale.append(entity.entity_id)
    return stale
