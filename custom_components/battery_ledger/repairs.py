"""Repairs: accept a revised spec from the BatteryLedger Store; choose how to work out return on investment."""

from __future__ import annotations

import json

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .config_flow import RoiSteps
from .const import CONF_GROUPS, CONF_SPEC
from .store_client import async_get_store_index

# Spec fields shown in the diff, by their names in the spec format (data, not prose).
_COMPARE = [
    ("capacity.usable_kwh", lambda s: s["capacity"]["usable_kwh"]),
    ("capacity.reported_kwh", lambda s: s["capacity"].get("reported_kwh")),
    ("warranty.years", lambda s: s["warranty"]["years"]),
    ("warranty.eol_capacity_pct", lambda s: s["warranty"]["eol_capacity_pct"]),
    ("warranty.throughput.basis", lambda s: s["warranty"]["throughput"]["basis"]),
    ("warranty.throughput", lambda s: json.dumps(
        {k: v for k, v in s["warranty"]["throughput"].items() if k in ("scope", "kwh", "table")})),
    ("phases", lambda s: ", ".join(s["phases"])),
    ("regions", lambda s: ", ".join(s["regions"])),
]


def _changes(old: dict, new: dict) -> str:
    lines = []
    for label, get in _COMPARE:
        try:
            a, b = get(old), get(new)
        except KeyError:
            continue
        if a != b:
            lines.append(f"- `{label}`: {a} → {b}")
    return "\n".join(lines) or "–"


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


class RoiRepairFlow(RoiSteps, RepairsFlow):
    """The ROI choice (the same form as Configure → ROI), asked for through Repairs until one is made."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id
        self._roi: dict = {}
        self._roi_plans: list[dict] = []

    @property
    def _roi_entry(self) -> ConfigEntry:
        return self.hass.config_entries.async_get_entry(self._entry_id)

    def _roi_done(self) -> FlowResult:
        return self.async_create_entry(data={})  # the notice goes once the choice is saved

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if self._roi_entry is None:
            return self.async_abort(reason="entry_gone")
        return await self.async_step_roi()


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict | None) -> RepairsFlow:
    # An issue without its data (shouldn't happen) still opens a flow, which aborts as spec_gone.
    data = data or {}
    if issue_id.startswith("roi_not_set_up_"):
        return RoiRepairFlow(data.get("entry_id", ""))
    return SpecUpdateRepairFlow(data.get("entry_id", ""), data.get("spec_id", ""))
