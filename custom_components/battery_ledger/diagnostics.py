"""Diagnostics for BatteryLedger (Settings → Devices & services → BatteryLedger → ⋮ → Download diagnostics).

For support: the setup, the source sensors' current readings and the latest calculation. Module serials are
replaced by M1, M2… and costs are removed, so the file can be attached to an issue.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CAPACITY_ENTITY,
    CONF_CHARGED_ENTITY,
    CONF_COST,
    CONF_DISCHARGED_ENTITY,
    CONF_MODULES,
    CONF_SOC_ENTITY,
    CONF_SOH_ENTITY,
    MOD_DISCHARGED,
    MOD_ID,
    MOD_SOC,
)
from .store_client import async_get_store_index

# Costs and what follows from them are the user's own business, not needed to diagnose a problem.
TO_REDACT = {CONF_COST, "cost_consumed", "cost_per_kwh_rated", "cost_per_kwh_projected", "cost_per_kwh_export",
             "remaining_value"}


def _source(hass: HomeAssistant, entity_id: str | None) -> dict[str, Any] | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    return {"entity_id": entity_id, "state": state.state if state else None,
            "unit": state.attributes.get("unit_of_measurement") if state else None}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    current = {**entry.data, **entry.options}
    # Module serials → M1, M2… consistently across the file
    alias = {m[MOD_ID]: f"M{i}" for i, m in enumerate(entry.data.get(CONF_MODULES) or [], start=1)}

    def anonymise(value: Any) -> Any:
        if isinstance(value, dict):
            return {alias.get(k, k): anonymise(v) for k, v in value.items()}
        if isinstance(value, list):
            return [anonymise(v) for v in value]
        if isinstance(value, str):
            for serial, name in alias.items():
                value = value.replace(serial, name)
        return value

    data = dict(entry.data)
    data[CONF_MODULES] = [
        {MOD_ID: alias[m[MOD_ID]], "group": m.get("group"),
         "discharged": _source(hass, m.get(MOD_DISCHARGED)), "soc": _source(hass, m.get(MOD_SOC))}
        for m in entry.data.get(CONF_MODULES) or []
    ]
    runtime = getattr(entry, "runtime_data", None)
    result = getattr(runtime, "result", None)
    index = await async_get_store_index(hass)
    return anonymise(async_redact_data({
        "entry": {"title": entry.title, "version": f"{entry.version}.{entry.minor_version}",
                  "data": data, "options": dict(entry.options)},
        "sources": {key: _source(hass, current.get(key)) for key in
                    (CONF_CHARGED_ENTITY, CONF_DISCHARGED_ENTITY, CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY,
                     CONF_SOC_ENTITY)},
        "result": asdict(result) if result is not None else None,
        "store": {"source": index.source, "generated": index.generated, "specs": len(index.specs)},
    }, TO_REDACT))
