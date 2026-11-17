"""Config and options flows for BatteryLedger.

Setup flow:
    user (menu) ─┬─ store_search → store_select (one or more models) ─┐
                 ├─ store_refresh → back to the menu                   ├─ group (once per model) → add_more (menu)
                 └─ manual ────────────────────────────────────────────┘        add_more: add another / sensors
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
    CONF_CURRENCY_STYLE,
    CURRENCY_STYLE_CODE,
    CURRENCY_STYLE_SYMBOL,
    CURRENCY_SYMBOLS,
    CONF_DISCHARGED_ENTITY,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
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
from .store_client import StoreIndexError, async_get_store_index, spec_label

_LOGGER = logging.getLogger(__name__)

CHEMISTRIES = ["LFP", "NMC", "NCA", "LTO", "Sodium-ion", "Lead-acid", "Other"]
BASES = ["unspecified", "charged", "discharged"]
SCOPES = ["per_unit", "per_system", "table", "none"]
UNIT_TYPES = ["module", "system"]

_num_box = lambda **kw: sel.NumberSelector(sel.NumberSelectorConfig(mode=sel.NumberSelectorMode.BOX, **kw))  # noqa: E731
_text = sel.TextSelector()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


DASH = "–"


def _num(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _spec_summary(spec: dict) -> dict[str, str]:
    """Description placeholders for a spec: data only, all wording is in strings.json."""
    cap, w = spec["capacity"], spec["warranty"]
    tp = w["throughput"]
    mwh = lambda kwh: f"{_num(kwh / 1000)} MWh"  # noqa: E731
    return {
        "name": " ".join(x for x in (spec["brand"], spec["model"], spec.get("variant")) if x),
        "spec_id": spec["id"],
        "version": str(spec.get("spec_version", DASH)),
        "regions": ", ".join(spec["regions"]),
        "phases": ", ".join(f"{p}φ" for p in spec["phases"]),
        "chemistry": spec.get("chemistry", DASH),
        "usable": _num(cap["usable_kwh"]),
        "years": _num(w["years"]),
        "eol": _num(w["eol_capacity_pct"]),
        "tp_unit": mwh(tp["kwh"]) if tp["scope"] == "per_unit" else DASH,
        "tp_system": mwh(tp["kwh"]) if tp["scope"] == "per_system" else DASH,
        "tp_table": ", ".join(f"{r['units']}× {mwh(r['kwh'])}" for r in tp["table"]) if tp["scope"] == "table" else DASH,
        "basis": tp["basis"],
        "verified": "✓" if spec.get("verified") else "✗",
        "sources": ", ".join(f"[{src.get('title') or src['url']}]({src['url']})" for src in spec.get("sources", [])) or DASH,
    }


def _allowed_units(spec: dict) -> str:
    tp, cap = spec["warranty"]["throughput"], spec["capacity"]
    if tp["scope"] == "table":
        return ", ".join(str(r["units"]) for r in tp["table"])
    return f"{cap.get('min_units', 1)}–{cap.get('max_units', 100)}"


def _energy_entity_selector() -> sel.EntitySelector:
    return sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor", device_class="energy"))


def _system_schema(defaults: dict[str, Any], *, with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required("name", default=defaults.get("name", NAME))] = _text
    fields.update({
        vol.Optional(CONF_COST): _num_box(min=0, max=10_000_000, step=0.01),
        # Symbol by default: matches the original YAML package ($, $/kWh).
        vol.Required(CONF_CURRENCY_STYLE, default=defaults.get(CONF_CURRENCY_STYLE, CURRENCY_STYLE_SYMBOL)):
            sel.SelectSelector(sel.SelectSelectorConfig(
                options=[CURRENCY_STYLE_CODE, CURRENCY_STYLE_SYMBOL], translation_key="currency_style",
                mode=sel.SelectSelectorMode.LIST)),
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


def _currency_placeholders(code: str) -> dict[str, str]:
    """Examples for the code / symbol choice, from Home Assistant's regional currency."""
    return {"currency": code, "symbol": CURRENCY_SYMBOLS.get(code, code)}


def _check_system(user_input: dict) -> dict[str, str]:
    if not user_input.get(CONF_CHARGED_ENTITY) and not user_input.get(CONF_DISCHARGED_ENTITY):
        return {"base": "no_energy_entity"}
    return {}


class BatteryLedgerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    def __init__(self) -> None:
        self._groups: list[dict] = []
        self._pending_spec: dict | None = None
        self._queue: list[dict] = []
        self._filters: dict[str, str] = {"search": "", "brand": ANY, "series": ANY, "region": ANY, "phase": ANY}
        self._matches: list[dict] = []
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
        return self.async_show_menu(
            step_id="user",
            menu_options=["store_search", "store_refresh", "manual"],
            description_placeholders={
                "count": str(len(index.specs)),
                "updated": (index.generated or DASH)[:10],
                "store_url": STORE_SITE_URL,
            },
        )

    async def async_step_store_refresh(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        try:
            count = await index.async_refresh()
        except StoreIndexError as err:
            return self.async_show_form(
                step_id="store_refresh_failed", data_schema=vol.Schema({}),
                description_placeholders={"error": str(err), "count": str(len(index.specs)),
                                          "updated": (index.generated or DASH)[:10]})
        return self.async_show_form(
            step_id="store_refresh_ok", data_schema=vol.Schema({}),
            description_placeholders={"count": str(count), "updated": (index.generated or DASH)[:10]})

    async def async_step_store_refresh_ok(self, user_input: dict | None = None) -> ConfigFlowResult:
        return await self.async_step_user()

    async def async_step_store_refresh_failed(self, user_input: dict | None = None) -> ConfigFlowResult:
        return await self.async_step_user()

    # --- Store search ----------------------------------------------------------

    async def async_step_store_search(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        errors: dict[str, str] = {}
        if user_input is not None:
            self._filters = {
                "search": user_input.get("search", "").strip(),
                "brand": user_input.get("brand") or ANY,
                "series": user_input.get("series") or ANY,
                "region": user_input.get("region") or ANY,
                "phase": user_input.get("phase") or ANY,
            }
            self._matches = index.search(self._filters["search"], self._filters["brand"],
                                         self._filters["region"], self._filters["phase"],
                                         self._filters["series"])
            if self._matches:
                return await self.async_step_store_select()
            errors["base"] = "no_matches"

        f = self._filters
        if f["region"] == ANY and not user_input and self.hass.config.country in index.regions():
            f["region"] = self.hass.config.country
        # Optional dropdowns: left empty means "any", so no English "Any ..." option labels.
        dropdown = lambda opts: sel.SelectSelector(  # noqa: E731
            sel.SelectSelectorConfig(options=opts, mode=sel.SelectSelectorMode.DROPDOWN))
        schema = vol.Schema({
            vol.Optional("search"): _text,
            vol.Optional("brand"): dropdown([sel.SelectOptionDict(value=b, label=b) for b in index.brands()]),
            vol.Optional("series"): dropdown([sel.SelectOptionDict(value=f"{b}|{sr}", label=f"{sr} ({b})")
                                              for b, sr in index.series()]),
            vol.Optional("region"): dropdown([sel.SelectOptionDict(value=r, label=r) for r in index.regions()]),
            vol.Optional("phase"): sel.SelectSelector(
                sel.SelectSelectorConfig(options=["1", "3"], translation_key="phase_only",
                                         mode=sel.SelectSelectorMode.DROPDOWN)),
        })
        schema = self.add_suggested_values_to_schema(
            schema, {k: v for k, v in f.items() if v and v != ANY})
        return self.async_show_form(
            step_id="store_search", data_schema=schema, errors=errors,
            description_placeholders={"count": str(len(index.specs)), "store_url": STORE_SITE_URL},
        )

    async def async_step_store_select(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            chosen = user_input.get("spec_ids") or []
            if chosen:
                self._queue = [s for s in self._matches if s["id"] in chosen]
                return await self.async_step_group()
            errors["base"] = "none_selected"
        options = [sel.SelectOptionDict(value=s["id"], label=spec_label(s)) for s in self._matches]
        mode = sel.SelectSelectorMode.LIST if len(options) <= 10 else sel.SelectSelectorMode.DROPDOWN
        default = [options[0]["value"]] if len(options) == 1 else []
        return self.async_show_form(
            step_id="store_select",
            data_schema=vol.Schema({
                vol.Required("spec_ids", default=default): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=options, mode=mode, multiple=True)),
            }),
            errors=errors,
            description_placeholders={"matches": str(len(options))},
        )

    # --- Manual entry ----------------------------------------------------------

    async def async_step_manual(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            spec, errors = self._manual_spec(user_input)
            if not errors:
                self._queue = [spec]
                return await self.async_step_group()

        country = self.hass.config.country or ""
        schema = vol.Schema({
            vol.Required("brand"): _text,
            vol.Optional("series"): _text,
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
        if ui.get("series"):
            spec["series"] = ui["series"].strip()
        if not errors and validate_spec(spec):
            errors["base"] = "invalid_spec"
            _LOGGER.debug("Manual spec rejected: %s", validate_spec(spec))
        return spec, errors

    # --- Battery group + system -----------------------------------------------

    async def async_step_group(self, user_input: dict | None = None) -> ConfigFlowResult:
        if self._pending_spec is None:
            self._pending_spec = self._queue.pop(0)
        spec = self._pending_spec
        errors: dict[str, str] = {}
        placeholders = {**_spec_summary(spec), "remaining": str(len(self._queue)),
                        "allowed": _allowed_units(spec)}
        if user_input is not None:
            units = int(user_input[CONF_UNITS])
            install = date.fromisoformat(user_input[CONF_INSTALL_DATE])
            try:
                validate_units(spec, units)
            except SpecError:
                errors[CONF_UNITS] = "bad_units"
            if install > dt_util.now().date():
                errors[CONF_INSTALL_DATE] = "future_date"
            if not errors:
                self._groups.append({CONF_SPEC: spec, CONF_UNITS: units, CONF_INSTALL_DATE: install.isoformat()})
                self._pending_spec = None
                if self._queue:
                    return await self.async_step_group()
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
            f"- {g[CONF_UNITS]} × {g[CONF_SPEC]['brand']} {g[CONF_SPEC]['model']} · {g[CONF_INSTALL_DATE]}"
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

        # Option labels are data (profile names, ✓/✗); "manual" is translated via translation_key.
        options: list[sel.SelectOptionDict] = []
        lines: list[str] = []
        for profile in profiles:
            found = per_profile[profile["id"]]
            for system in found:
                options.append(sel.SelectOptionDict(value=system.value, label=system.label(len(found) > 1)))
                lines.append(f"- {system.label(len(found) > 1)}: {len(system.roles)} · {len(system.modules)}")
            if not found:
                options.append(sel.SelectOptionDict(value=f"{profile['id']}|none", label=f"{profile['name']} ✗"))
                lines.append(f"- {profile['name']}: ✗")
        options.append(sel.SelectOptionDict(value=MANUAL, label=MANUAL))
        default = next(iter(self._detected), MANUAL)
        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema({
                vol.Required("integration", default=default): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=options, mode=sel.SelectSelectorMode.LIST,
                                             translation_key="integration")),
            }),
            errors=errors,
            description_placeholders={
                "brands": ", ".join(sorted(brands)),
                "count": str(len(profiles)),
                "found": "\n".join(lines) or DASH,
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
        assignment, unassigned, counts = assign_modules(rated, group_caps)
        problems = bool(unassigned) or any(found != want for found, want in counts)

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
            cap = f"{_num(rated[mid])} kWh" if rated[mid] is not None else "?"
            lines.append(f"- {mid}: {cap} → {self._groups[grp][CONF_SPEC]['model'] if grp is not None else '✗'}")
        per_group = "\n".join(
            f"- {g[CONF_SPEC]['model']}: {found} / {want} {'✓' if found == want else '✗'}"
            for g, (found, want) in zip(self._groups, counts))
        return self.async_show_form(
            step_id="modules",
            data_schema=vol.Schema({vol.Required(CONF_USE_MODULES, default=not problems): sel.BooleanSelector()}),
            description_placeholders={
                "count": str(len(mods)),
                "modules": "\n".join(lines),
                "per_group": per_group,
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
        # Brand in title form + "Battery": e.g. "Sigenergy Battery", "Sungrow Battery".
        defaults = {"name": f"{first['brand']} Battery"}
        schema = _system_schema(defaults, with_name=True)
        suggested = dict(user_input or {})
        if user_input is None and self._system:
            suggested = {ROLE_TO_CONF[r]: eid for r, (_lvl, eid) in self._system.roles.items() if r in ROLE_TO_CONF}
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)
        sysd = self._system
        return self.async_show_form(step_id="system", data_schema=schema, errors=errors, description_placeholders={
            "profile": sysd.profile_name if sysd else DASH,
            "filled": str(len([r for r in sysd.roles if r in ROLE_TO_CONF])) if sysd else "0",
            "ambiguous": ", ".join(sysd.ambiguous) if sysd and sysd.ambiguous else DASH,
            "modules": str(len(self._modules)),
            **_currency_placeholders(self.hass.config.currency),
        })


class BatteryLedgerOptionsFlow(OptionsFlow):
    """Change cost, currency and sensors after setup."""

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_system(user_input)
            if not errors:
                # Store every field so a cleared optional field overrides setup data.
                data = {k: user_input.get(k) for k in
                        (CONF_COST, CONF_CURRENCY_STYLE, CONF_CHARGED_ENTITY, CONF_DISCHARGED_ENTITY,
                         CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY)}
                return self.async_create_entry(data=data)
        current = {**self.config_entry.data, **self.config_entry.options}
        schema = _system_schema({CONF_CURRENCY_STYLE: current.get(CONF_CURRENCY_STYLE, CURRENCY_STYLE_CODE)},
                                with_name=False)
        schema = self.add_suggested_values_to_schema(schema, user_input or current)
        code = current.get(CONF_CURRENCY) or self.hass.config.currency
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors,
                                    description_placeholders=_currency_placeholders(code))
