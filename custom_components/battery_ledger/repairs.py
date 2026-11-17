"""Repairs: accept a revised spec from the BatteryLedger Store."""

from __future__ import annotations

import json

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_GROUPS, CONF_SPEC
from .store_client import async_get_store_index

_COMPARE = [
    ("Usable capacity (kWh)", lambda s: s["capacity"]["usable_kwh"]),
    ("Reported capacity (kWh)", lambda s: s["capacity"].get("reported_kwh")),
    ("Warranty years", lambda s: s["warranty"]["years"]),
    ("End-of-life capacity (%)", lambda s: s["warranty"]["eol_capacity_pct"]),
    ("Throughput basis", lambda s: s["warranty"]["throughput"]["basis"]),
    ("Throughput limit", lambda s: json.dumps(
        {k: v for k, v in s["warranty"]["throughput"].items() if k in ("scope", "kwh", "table")})),
    ("Phases", lambda s: ", ".join(s["phases"])),
    ("Regions", lambda s: ", ".join(s["regions"])),
]


def _changes(old: dict, new: dict) -> str:
    lines = []
    for label, get in _COMPARE:
        try:
            a, b = get(old), get(new)
        except KeyError:
            continue
        if a != b:
            lines.append(f"- {label}: {a} → {b}")
    return "\n".join(lines) or "- No changes to the figures BatteryLedger uses (notes or sources only)."


class SpecUpdateRepairFlow(RepairsFlow):
    def __init__(self, entry_id: str, spec_id: str) -> None:
        self.entry_id = entry_id
        self.spec_id = spec_id

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        index = await async_get_store_index(self.hass)
        latest = index.get(self.spec_id)
        if entry is None or latest is None:
            return self.async_abort(reason="spec_gone")
        groups = entry.data[CONF_GROUPS]
        current = next((g[CONF_SPEC] for g in groups if g[CONF_SPEC]["id"] == self.spec_id), None)
        if current is None:
            return self.async_abort(reason="spec_gone")

        if user_input is not None:
            new_groups = [
                {**g, CONF_SPEC: latest} if g[CONF_SPEC]["id"] == self.spec_id else g for g in groups
            ]
            # The entry's update listener reloads it, which clears this repair.
            self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_GROUPS: new_groups})
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "model": f"{current['brand']} {current['model']}",
                "old": str(current.get("spec_version")),
                "new": str(latest.get("spec_version")),
                "changes": _changes(current, latest),
            },
        )


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict | None) -> RepairsFlow:
    assert data is not None
    return SpecUpdateRepairFlow(data["entry_id"], data["spec_id"])
