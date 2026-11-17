"""Config and options flows for BatteryLedger.

Setup flow:
    user (menu) ─┬─ store_search → store_select → store_confirm ─┐
                 ├─ store_refresh → back to the menu              ├─ group → add_more (menu) ─┬─ (add another)
                 └─ manual ───────────────────────────────────────┘                          └─ sensors
    sensors (pick integration / detected system) → [modules] → system → entry
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector as sel
from homeassistant.util import dt as dt_util

from .const import (
    ANY,
    CONF_CAPACITY_ENTITY,
    CONF_CHARGED_ENTITY,
    CONF_COST,
    CONF_CURRENCY,
    CONF_DISCHARGED_ENTITY,
    CONF_GROUPS,
    CONF_INSTALL_DATE,
    CONF_MODULES,
    CONF_PROFILE,
    CONF_SOH_ENTITY,
    CONF_SPEC,
    CONF_UNITS,
    CONF_USE_MODULES,
    DOMAIN,
    MANUAL,
    MANUAL_ID_PREFIX,
    MOD_DISCHARGED,
    MOD_GROUP,
    MOD_ID,
    MOD_SOC,
    NAME,
    SPEC_SOURCE_MANUAL,
    STORE_SITE_URL,
)
from .detect import DetectedSystem, RegistryEntity, assign_modules, detect
from .ledger import SpecError, validate_spec, validate_units
from .store_client import SOURCE_BUNDLED, StoreIndexError, async_get_store_index, spec_label

_LOGGER = logging.getLogger(__name__)

CHEMISTRIES = ["LFP", "NMC", "NCA", "LTO", "Sodium-ion", "Lead-acid", "Other"]
BASES = ["unspecified", "charged", "discharged"]
SCOPES = ["per_unit", "per_system", "table", "none"]
UNIT_TYPES = ["module", "system"]

_num_box = lambda **kw: sel.NumberSelector(sel.NumberSelectorConfig(mode=sel.NumberSelectorMode.BOX, **kw))  # noqa: E731
_text = sel.TextSelector()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _spec_summary(spec: dict) -> dict[str, str]:
    """Description placeholders describing a spec."""
    cap, w = spec["capacity"], spec["warranty"]
    tp = w["throughput"]
    if tp["scope"] == "none":
        tp_text = "no throughput limit"
    elif tp["scope"] == "table":
        tp_text = ", ".join(f"{r['units']} units: {r['kwh'] / 1000:,.2f} MWh" for r in tp["table"])
    else:
        tp_text = f"{tp['kwh'] / 1000:,.2f} MWh {'per unit' if tp['scope'] == 'per_unit' else 'per system'}"
    basis = {"charged": "charged energy", "discharged": "discharged energy",
             "unspecified": "not stated by the warranty"}[tp["basis"]]
    sources = ", ".join(f"[{s.get('title') or 'source'}]({s['url']})" for s in spec.get("sources", [])) or "none"
    return {
        "name": f"{spec['brand']} {spec['model']}" + (f" {spec['variant']}" if spec.get("variant") else ""),
        "spec_id": spec["id"],
        "version": str(spec.get("spec_version", "-")),
        "regions": ", ".join(spec["regions"]),
        "phases": " and ".join("single phase" if p == "1" else "three phase" for p in spec["phases"]),
        "chemistry": spec.get("chemistry", "-"),
        "usable": f"{cap['usable_kwh']:g} kWh per {'module' if cap['unit'] == 'module' else 'system'}",
        "warranty": f"{w['years']:g} years to {w['eol_capacity_pct']:g}%",
        "throughput": tp_text,
        "basis": basis,
        "verified": "Yes" if spec.get("verified") else "No - figures not yet checked by a maintainer",
        "sources": sources,
    }


def _energy_entity_selector() -> sel.EntitySelector:
    return sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor", device_class="energy"))


def _system_schema(defaults: dict[str, Any], *, with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required("name", default=defaults.get("name", NAME))] = _text
    fields.update({
        vol.Optional(CONF_COST): _num_box(min=0, max=10_000_000, step=0.01),
        vol.Required(CONF_CURRENCY, default=defaults.get(CONF_CURRENCY, "")): _text,
        vol.Optional(CONF_CHARGED_ENTITY): _energy_entity_selector(),
        vol.Optional(CONF_DISCHARGED_ENTITY): _energy_entity_selector(),
        vol.Optional(CONF_CAPACITY_ENTITY): sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor")),
        vol.Optional(CONF_SOH_ENTITY): sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor")),
    })
    return vol.Schema(fields)


ROLE_TO_CONF = {
    "charged_energy": CONF_CHARGED_ENTITY,
    "discharged_energy": CONF_DISCHARGED_ENTITY,
    "rated_capacity": CONF_CAPACITY_ENTITY,
    "soh": CONF_SOH_ENTITY,
}


def _check_system(user_input: dict) -> dict[str, str]:
    if not user_input.get(CONF_CHARGED_ENTITY) and not user_input.get(CONF_DISCHARGED_ENTITY):
        return {"base": "no_energy_entity"}
    return {}


class BatteryLedgerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._groups: list[dict] = []
        self._pending_spec: dict | None = None
        self._filters: dict[str, str] = {"search": "", "brand": ANY, "region": ANY, "phase": ANY}
        self._matches: list[dict] = []
        self._status = ""
        self._detected: dict[str, DetectedSystem] = {}
        self._system: DetectedSystem | None = None
        self._modules: list[dict] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BatteryLedgerOptionsFlow()

    # --- start ---------------------------------------------------------------

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        await index.async_refresh_if_stale()
        when = index.fetched_at.astimezone(dt_util.get_default_time_zone()).strftime("%Y-%m-%d %H:%M") \
            if index.fetched_at else "never (using the copy bundled with BatteryLedger)"
        return self.async_show_menu(
            step_id="user",
            menu_options=["store_search", "store_refresh", "manual"],
            description_placeholders={
                "count": str(len(index.specs)),
                "updated": when,
                "status": self._status,
                "store_url": STORE_SITE_URL,
            },
        )

    async def async_step_store_refresh(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        try:
            count = await index.async_refresh()
            self._status = f"✅ Store list updated: {count} batteries available."
        except StoreIndexError as err:
            note = " Using the copy bundled with BatteryLedger." if index.source == SOURCE_BUNDLED else ""
            self._status = f"⚠️ Couldn't update the Store list ({err}).{note}"
        return await self.async_step_user()

    # --- Store search ----------------------------------------------------------

    async def async_step_store_search(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        errors: dict[str, str] = {}
        if user_input is not None:
            self._filters = {
                "search": user_input.get("search", "").strip(),
                "brand": user_input["brand"],
                "region": user_input["region"],
                "phase": user_input["phase"],
            }
            self._matches = index.search(self._filters["search"], self._filters["brand"],
                                         self._filters["region"], self._filters["phase"])
            if self._matches:
                return await self.async_step_store_select()
            errors["base"] = "no_matches"

        f = self._filters
        if f["region"] == ANY and not user_input and self.hass.config.country in index.regions():
            f["region"] = self.hass.config.country
        brand_opts = [sel.SelectOptionDict(value=ANY, label="Any brand")] + [
            sel.SelectOptionDict(value=b, label=b) for b in index.brands()]
        region_opts = [sel.SelectOptionDict(value=ANY, label="Any region")] + [
            sel.SelectOptionDict(value=r, label=r) for r in index.regions()]
        schema = vol.Schema({
            vol.Optional("search", default=f["search"]): _text,
            vol.Required("brand", default=f["brand"]): sel.SelectSelector(
                sel.SelectSelectorConfig(options=brand_opts, mode=sel.SelectSelectorMode.DROPDOWN)),
            vol.Required("region", default=f["region"]): sel.SelectSelector(
                sel.SelectSelectorConfig(options=region_opts, mode=sel.SelectSelectorMode.DROPDOWN)),
            vol.Required("phase", default=f["phase"]): sel.SelectSelector(
                sel.SelectSelectorConfig(options=[ANY, "1", "3"], translation_key="phase",
                                         mode=sel.SelectSelectorMode.DROPDOWN)),
        })
        return self.async_show_form(
            step_id="store_search", data_schema=schema, errors=errors,
            description_placeholders={"count": str(len(index.specs)), "store_url": STORE_SITE_URL},
        )

    async def async_step_store_select(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None and "spec_id" in user_input:
            self._pending_spec = next(s for s in self._matches if s["id"] == user_input["spec_id"])
            return await self.async_step_store_confirm()
        options = [sel.SelectOptionDict(value=s["id"], label=spec_label(s)) for s in self._matches]
        mode = sel.SelectSelectorMode.LIST if len(options) <= 8 else sel.SelectSelectorMode.DROPDOWN
        return self.async_show_form(
            step_id="store_select",
            data_schema=vol.Schema({
                vol.Required("spec_id", default=options[0]["value"]): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=options, mode=mode)),
            }),
            description_placeholders={"matches": str(len(options))},
        )

    async def async_step_store_confirm(self, user_input: dict | None = None) -> ConfigFlowResult:
        assert self._pending_spec is not None
        if user_input is not None:
            return await self.async_step_group()
        return self.async_show_form(
            step_id="store_confirm", data_schema=vol.Schema({}),
            description_placeholders=_spec_summary(self._pending_spec),
        )

    # --- Manual entry ----------------------------------------------------------

    async def async_step_manual(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            spec, errors = self._manual_spec(user_input)
            if not errors:
                self._pending_spec = spec
                return await self.async_step_group()

        country = self.hass.config.country or ""
        schema = vol.Schema({
            vol.Required("brand"): _text,
            vol.Required("model"): _text,
            vol.Optional("variant"): _text,
            vol.Required("regions", default=country): _text,
            vol.Required("chemistry", default="LFP"): sel.SelectSelector(
                sel.SelectSelectorConfig(options=CHEMISTRIES, mode=sel.SelectSelectorMode.DROPDOWN)),
            vol.Required("phases", default=["1"]): sel.SelectSelector(
                sel.SelectSelectorConfig(options=["1", "3"], multiple=True, translation_key="phase_only",
                                         mode=sel.SelectSelectorMode.LIST)),
            vol.Required("unit_type", default="module"): sel.SelectSelector(
                sel.SelectSelectorConfig(options=UNIT_TYPES, translation_key="unit_type")),
            vol.Required("usable_kwh"): _num_box(min=0, max=1000, step=0.01),
            vol.Optional("nominal_kwh"): _num_box(min=0, max=1000, step=0.01),
            vol.Optional("reported_kwh"): _num_box(min=0, max=1000, step=0.01),
            vol.Optional("max_units"): _num_box(min=1, max=100, step=1),
            vol.Required("warranty_years", default=10): _num_box(min=1, max=30, step=0.5),
            vol.Required("eol_capacity_pct", default=70): _num_box(min=0, max=100, step=1),
            vol.Required("throughput_basis", default="unspecified"): sel.SelectSelector(
                sel.SelectSelectorConfig(options=BASES, translation_key="throughput_basis")),
            vol.Required("throughput_scope", default="per_unit"): sel.SelectSelector(
                sel.SelectSelectorConfig(options=SCOPES, translation_key="throughput_scope")),
            vol.Optional("throughput_kwh"): _num_box(min=0, max=100_000_000, step=1),
            vol.Optional("throughput_table"): sel.TextSelector(sel.TextSelectorConfig(multiline=True)),
        })
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    def _manual_spec(self, ui: dict) -> tuple[dict, dict[str, str]]:
        errors: dict[str, str] = {}
        regions = [r.upper() for r in re.split(r"[,\s]+", ui["regions"]) if r]
        if not regions or not all(re.fullmatch(r"[A-Z]{2}|GLOBAL", r) for r in regions):
            errors["regions"] = "bad_regions"
        if not ui["phases"]:
            errors["phases"] = "no_phases"

        scope = ui["throughput_scope"]
        tp: dict[str, Any] = {"basis": ui["throughput_basis"], "scope": scope}
        if scope in ("per_unit", "per_system"):
            if not ui.get("throughput_kwh"):
                errors["throughput_kwh"] = "throughput_required"
            else:
                tp["kwh"] = float(ui["throughput_kwh"])
        elif scope == "table":
            rows = []
            for line in (ui.get("throughput_table") or "").splitlines():
                if not line.strip():
                    continue
                m = re.fullmatch(r"\s*(\d+)\s*=\s*([\d.,]+)\s*", line)
                if not m:
                    errors["throughput_table"] = "bad_table"
                    break
                rows.append({"units": int(m.group(1)), "kwh": float(m.group(2).replace(",", ""))})
            if not rows and "throughput_table" not in errors:
                errors["throughput_table"] = "bad_table"
            tp["table"] = sorted(rows, key=lambda r: r["units"])

        cap: dict[str, Any] = {"unit": ui["unit_type"], "usable_kwh": float(ui["usable_kwh"])}
        for key in ("nominal_kwh", "reported_kwh"):
            if ui.get(key):
                cap[key] = float(ui[key])
        if ui.get("max_units"):
            cap["max_units"] = int(ui["max_units"])

        spec = {
            "schema_version": 1,
            "id": MANUAL_ID_PREFIX + "-".join(
                _slug(x) for x in (ui["brand"], ui["model"], ui.get("variant", "")) if x),
            "spec_version": 0,
            "source": SPEC_SOURCE_MANUAL,
            "brand": ui["brand"].strip(),
            "model": ui["model"].strip(),
            "regions": regions,
            "chemistry": ui["chemistry"],
            "phases": sorted(ui["phases"]),
            "capacity": cap,
            "warranty": {"years": float(ui["warranty_years"]),
                         "eol_capacity_pct": float(ui["eol_capacity_pct"]), "throughput": tp},
            "sources": [],
        }
        if ui.get("variant"):
            spec["variant"] = ui["variant"].strip()
        if not errors and validate_spec(spec):
            errors["base"] = "invalid_spec"
            _LOGGER.debug("Manual spec rejected: %s", validate_spec(spec))
        return spec, errors

    # --- Battery group + system -----------------------------------------------

    async def async_step_group(self, user_input: dict | None = None) -> ConfigFlowResult:
        spec = self._pending_spec
        assert spec is not None
        errors: dict[str, str] = {}
        placeholders = {"name": f"{spec['brand']} {spec['model']}", "error": ""}
        if user_input is not None:
            units = int(user_input[CONF_UNITS])
            install = date.fromisoformat(user_input[CONF_INSTALL_DATE])
            try:
                validate_units(spec, units)
            except SpecError as err:
                errors[CONF_UNITS] = "bad_units"
                placeholders["error"] = str(err)
            if install > dt_util.now().date():
                errors[CONF_INSTALL_DATE] = "future_date"
            if not errors:
                self._groups.append({CONF_SPEC: spec, CONF_UNITS: units, CONF_INSTALL_DATE: install.isoformat()})
                self._pending_spec = None
                return await self.async_step_add_more()

        cap = spec["capacity"]
        is_module = cap["unit"] == "module"
        schema = vol.Schema({
            vol.Required(CONF_UNITS, default=cap.get("min_units", 1)): _num_box(
                min=cap.get("min_units", 1), max=cap.get("max_units", 100 if is_module else 20), step=1),
            vol.Required(CONF_INSTALL_DATE): sel.DateSelector(),
        })
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="group", data_schema=schema, errors=errors,
                                    description_placeholders=placeholders)

    async def async_step_add_more(self, user_input: dict | None = None) -> ConfigFlowResult:
        summary = "\n".join(
            f"- {g[CONF_UNITS]} × {g[CONF_SPEC]['brand']} {g[CONF_SPEC]['model']}, installed {g[CONF_INSTALL_DATE]}"
            for g in self._groups)
        return self.async_show_menu(
            step_id="add_more", menu_options=["sensors", "store_search", "manual"],
            description_placeholders={"groups": summary},
        )

    # --- Sensors: Store sensor profiles -------------------------------------------

    async def async_step_sensors(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        brands = {g[CONF_SPEC]["brand"] for g in self._groups}
        profiles = index.profiles_for_brands(brands)
        errors: dict[str, str] = {}

        if user_input is not None:
            choice = user_input["integration"]
            if choice == MANUAL:
                self._system = None
                return await self.async_step_system()
            if choice in self._detected:
                self._system = self._detected[choice]
                if self._system.modules and self._system.modules_usable:
                    return await self.async_step_modules()
                return await self.async_step_system()
            errors["integration"] = "not_detected"

        registry = er.async_get(self.hass)
        entities = [RegistryEntity(e.entity_id, e.platform, e.unique_id)
                    for e in registry.entities.values() if not e.disabled]
        self._detected = {}
        per_profile: dict[str, list[DetectedSystem]] = {}
        for profile in profiles:
            found = detect(profile, entities)
            per_profile[profile["id"]] = found
            for system in found:
                system.modules_usable = any("module_discharged_energy" in m for m in system.modules.values())
                self._detected[system.value] = system

        options: list[sel.SelectOptionDict] = []
        for profile in profiles:
            found = per_profile[profile["id"]]
            for system in found:
                options.append(sel.SelectOptionDict(value=system.value, label=system.label(len(found) > 1)))
            if not found:
                options.append(sel.SelectOptionDict(
                    value=f"{profile['id']}|none", label=f"{profile['name']} — not found in Home Assistant"))
        options.append(sel.SelectOptionDict(value=MANUAL, label="Choose sensors myself"))
        default = next(iter(self._detected), MANUAL)
        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema({
                vol.Required("integration", default=default): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=options, mode=sel.SelectSelectorMode.LIST)),
            }),
            errors=errors,
            description_placeholders={
                "brands": ", ".join(sorted(brands)),
                "count": str(len(profiles)),
                "store_url": STORE_SITE_URL,
            },
        )

    def _read_float(self, entity_id: str | None) -> float | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        try:
            return float(state.state) if state else None
        except ValueError:
            return None

    async def async_step_modules(self, user_input: dict | None = None) -> ConfigFlowResult:
        assert self._system is not None
        mods = {mid: roles for mid, roles in self._system.modules.items() if "module_discharged_energy" in roles}
        rated = {mid: self._read_float(r.get("module_rated_capacity")) for mid, r in mods.items()}
        group_caps = [
            (g[CONF_SPEC]["capacity"].get("reported_kwh", g[CONF_SPEC]["capacity"].get("nominal_kwh")), g[CONF_UNITS])
            for g in self._groups
        ]
        assignment, problems = assign_modules(rated, group_caps)

        if user_input is not None:
            self._modules = []
            if user_input[CONF_USE_MODULES]:
                self._modules = [
                    {MOD_ID: mid, MOD_GROUP: grp,
                     MOD_DISCHARGED: mods[mid]["module_discharged_energy"],
                     MOD_SOC: mods[mid].get("module_soc")}
                    for mid, grp in assignment.items()
                ]
            return await self.async_step_system()

        lines = []
        for mid in sorted(mods):
            grp = assignment.get(mid)
            spec = self._groups[grp][CONF_SPEC] if grp is not None else None
            cap = f"{rated[mid]:g} kWh" if rated[mid] is not None else "capacity unknown"
            lines.append(f"- {mid}: {cap} → {spec['model'] if spec else 'not assigned'}")
        return self.async_show_form(
            step_id="modules",
            data_schema=vol.Schema({vol.Required(CONF_USE_MODULES, default=not problems): sel.BooleanSelector()}),
            description_placeholders={
                "count": str(len(mods)),
                "modules": "\n".join(lines),
                "problems": ("\n\n⚠️ " + "\n⚠️ ".join(problems)) if problems else "",
            },
        )

    async def async_step_system(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_system(user_input)
            if not errors:
                name = user_input.pop("name").strip() or NAME
                return self.async_create_entry(title=name, data={
                    **user_input,
                    CONF_GROUPS: self._groups,
                    CONF_PROFILE: self._system.profile_id if self._system else None,
                    CONF_MODULES: self._modules,
                })
        first = self._groups[0][CONF_SPEC]
        defaults = {"name": f"{first['brand']} battery", CONF_CURRENCY: self.hass.config.currency}
        schema = _system_schema(defaults, with_name=True)
        suggested = dict(user_input or {})
        if user_input is None and self._system:
            suggested = {ROLE_TO_CONF[r]: eid for r, (_lvl, eid) in self._system.roles.items() if r in ROLE_TO_CONF}
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)
        detected = ""
        if self._system:
            levels = ", ".join(f"{r.replace('_', ' ')} ({lvl})" for r, (lvl, _e) in self._system.roles.items())
            detected = f"Filled in from {self._system.profile_name}: {levels or 'nothing'}."
            if self._system.ambiguous:
                detected += (" Several inverter-level sensors matched for "
                             f"{', '.join(r.replace('_', ' ') for r in self._system.ambiguous)}, so choose those yourself.")
            if self._modules:
                detected += f" Tracking {len(self._modules)} battery modules individually."
        return self.async_show_form(step_id="system", data_schema=schema, errors=errors,
                                    description_placeholders={"detected": detected})


class BatteryLedgerOptionsFlow(OptionsFlow):
    """Change cost, currency and sensors after setup."""

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_system(user_input)
            if not errors:
                # Store every field so a cleared optional field overrides setup data.
                data = {k: user_input.get(k) for k in
                        (CONF_COST, CONF_CURRENCY, CONF_CHARGED_ENTITY, CONF_DISCHARGED_ENTITY,
                         CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY)}
                return self.async_create_entry(data=data)
        current = {**self.config_entry.data, **self.config_entry.options}
        schema = _system_schema({CONF_CURRENCY: current.get(CONF_CURRENCY) or self.hass.config.currency},
                                with_name=False)
        schema = self.add_suggested_values_to_schema(schema, user_input or current)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
