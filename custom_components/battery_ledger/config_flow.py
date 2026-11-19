"""Config and options flows for BatteryLedger.

Setup flow:
    user (menu) ─┬─ detect → [detect_enable → detect_wait] → detect_result ─→ group / store_select / store_search
                 ├─ store_search → store_select (one or more models) ─┐
                 ├─ store_refresh → back to the menu                   ├─ group (once per model) → add_more (menu)
                 └─ manual ────────────────────────────────────────────┘        add_more: add another / sensors
    sensors (pick integration / detected system) → [modules] → system → entry
"""

from __future__ import annotations

import asyncio
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
from .suggest import Reading, suggest
from .ledger import SpecError, validate_spec, validate_units
from .store_client import StoreIndexError, async_get_store_index, spec_label

_LOGGER = logging.getLogger(__name__)

CHEMISTRIES = ["LFP", "NMC", "NCA", "LTO", "Sodium-ion", "Lead-acid", "Other"]
BASES = ["unspecified", "charged", "discharged"]
SCOPES = ["per_unit", "per_system", "table", "none"]
UNIT_TYPES = ["module", "system"]

# After enabling sensors in setup: look for their first readings after each of these waits, then carry
# on with whatever has reported (the integration reloads about 30 s after an entity is enabled, then polls).
ENABLE_WAIT_ATTEMPTS = (45, 45)
_NO_VALUE = ("unknown", "unavailable", "", "none", "None", "0")

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


def _models_in(specs: list[dict]) -> list[tuple[str, str]]:
    """(brand, model line) pairs present in these specs, in Store order. Specs without a line are skipped."""
    return list(dict.fromkeys((s["brand"], s["series"]) for s in specs if s.get("series")))


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


def _read_float(hass, entity_id: str | None) -> float | None:
    state = hass.states.get(entity_id) if entity_id else None
    try:
        return float(state.state) if state else None
    except ValueError:
        return None


def _registry_entities(hass, *, include_disabled: bool = False) -> list[RegistryEntity]:
    registry = er.async_get(hass)
    return [RegistryEntity(e.entity_id, e.platform, e.unique_id)
            for e in registry.entities.values() if include_disabled or not e.disabled]


async def _async_helper_value(hass, brand: str, role: str) -> str | None:
    """State of a system role (e.g. an install-date helper) from a profile for this brand."""
    index = await async_get_store_index(hass)
    profiles = [p for p in index.profiles_for_brands({brand}) if role in p.get("roles", {})]
    if not profiles:
        return None
    entities = _registry_entities(hass)
    for profile in profiles:
        for system in detect(profile, entities):
            if role in system.roles:
                state = hass.states.get(system.roles[role][1])
                if state and state.state not in ("unknown", "unavailable", ""):
                    return state.state
    return None


async def _async_group_prefill(hass, spec: dict, n: int, units: int | None = None) -> dict[str, Any]:
    """Units, warranty start and cost for battery group number n (0-based), from detection or helpers.

    The first group takes an integration's install date and cost (e.g. Energy Manager's
    battery_install_date / battery_install_cost), the second its "_2" pair, and so on where they exist.
    """
    suffix = "" if n == 0 else f"_{n + 1}"
    out: dict[str, Any] = {CONF_UNITS: units}
    install = await _async_helper_value(hass, spec["brand"], f"install_date{suffix}")
    try:
        found = date.fromisoformat(install[:10]) if install else None
    except ValueError:
        found = None
    if found and found <= dt_util.now().date():
        out[CONF_INSTALL_DATE] = found.isoformat()
    cost = await _async_helper_value(hass, spec["brand"], f"install_cost{suffix}")
    try:
        out[CONF_COST] = float(cost) if cost and float(cost) > 0 else None
    except ValueError:
        pass
    return out


def _cost_box() -> sel.NumberSelector:
    return _num_box(min=0, max=10_000_000, step=0.01)


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
        # Units suggested by detection, by spec ID (pre-filled on the group step for the user to confirm).
        self._suggested_units: dict[str, int] = {}
        # Units for each queued spec when detection decided them (several groups can share a spec).
        self._queue_units: list[int | None] = []
        self._pending_units: int | None = None
        # Detection: candidate systems from every sensor profile, entities to enable, the wait task.
        self._found: dict[str, tuple[dict, DetectedSystem]] = {}
        self._to_enable: list[str] = []
        self._wait_task: asyncio.Task | None = None

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
            menu_options=["detect", "store_search", "store_refresh", "manual"],
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

    # --- Detect from the battery's integration ---------------------------------------

    async def async_step_detect(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        if user_input is not None:
            profile, system = self._found[user_input["system"]]
            self._system = system
            self._to_enable = self._disabled_entities(system)
            if self._to_enable:
                return await self.async_step_detect_enable()
            return await self.async_step_detect_result()

        entities = _registry_entities(self.hass, include_disabled=True)
        self._found = {}
        for profile in index.profiles:
            for system in detect(profile, entities):
                self._found[system.value] = (profile, system)
        if not self._found:
            return self.async_show_form(step_id="detect_none", data_schema=vol.Schema({}))
        per_profile: dict[str, int] = {}
        for p, _system in self._found.values():
            per_profile[p["id"]] = per_profile.get(p["id"], 0) + 1
        # Labels are data: profile name, plus the system key when one integration has several.
        options = [sel.SelectOptionDict(value=v, label=system.label(per_profile[p["id"]] > 1))
                   for v, (p, system) in self._found.items()]
        return self.async_show_form(step_id="detect", data_schema=vol.Schema({
            vol.Required("system", default=options[0]["value"]): sel.SelectSelector(
                sel.SelectSelectorConfig(options=options, mode=sel.SelectSelectorMode.LIST)),
        }), description_placeholders={"count": str(len(options))})

    async def async_step_detect_none(self, user_input: dict | None = None) -> ConfigFlowResult:
        return await self.async_step_store_search()

    def _system_entities(self, system: DetectedSystem) -> list[str]:
        ids = [eid for _lvl, eid in system.roles.values()]
        ids += [eid for roles in system.inverters.values() for found in roles.values() for eid in found]
        ids += [eid for roles in system.modules.values() for eid in roles.values()]
        return list(dict.fromkeys(ids))

    def _disabled_entities(self, system: DetectedSystem) -> list[str]:
        """Entities of this system that their integration disabled by default (never ones the user disabled)."""
        registry = er.async_get(self.hass)
        out = []
        for eid in self._system_entities(system):
            entry = registry.async_get(eid)
            if entry and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                out.append(eid)
        return out

    async def async_step_detect_enable(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input.get("enable"):
                registry = er.async_get(self.hass)
                for eid in self._to_enable:
                    registry.async_update_entity(eid, disabled_by=None)
                return await self.async_step_detect_wait()
            return await self.async_step_detect_result()
        return self.async_show_form(
            step_id="detect_enable",
            data_schema=vol.Schema({vol.Required("enable", default=True): sel.BooleanSelector()}),
            description_placeholders={"count": str(len(self._to_enable)),
                                      "entities": "\n".join(f"- `{e}`" for e in self._to_enable)})

    async def async_step_detect_wait(self, user_input: dict | None = None) -> ConfigFlowResult:
        if self._wait_task is None:
            self._wait_task = self.hass.async_create_task(self._async_wait_for(self._to_enable))
        if not self._wait_task.done():
            return self.async_show_progress(
                step_id="detect_wait", progress_action="wait_sensors", progress_task=self._wait_task,
                description_placeholders={"count": str(len(self._to_enable))})
        self._wait_task = None
        return self.async_show_progress_done(next_step_id="detect_result")

    async def _async_wait_for(self, entity_ids: list[str]) -> None:
        """Wait, check every entity has a reading; if not, wait and check once more."""
        for delay in ENABLE_WAIT_ATTEMPTS:
            await asyncio.sleep(delay)
            states = [self.hass.states.get(e) for e in entity_ids]
            if all(st and st.state not in ("unknown", "unavailable") for st in states):
                return

    def _state(self, entity_id: str | None) -> str | None:
        st = self.hass.states.get(entity_id) if entity_id else None
        return st.state if st and st.state not in ("unknown", "unavailable") else None

    def _kwh(self, entity_id: str | None) -> float | None:
        """A capacity reading in kWh (Wh and MWh converted)."""
        st = self.hass.states.get(entity_id) if entity_id else None
        try:
            value = float(st.state) if st else None
        except ValueError:
            return None
        if value is None:
            return None
        unit = st.attributes.get("unit_of_measurement")
        return value / 1000 if unit == "Wh" else value * 1000 if unit == "MWh" else value

    def _int(self, entity_id: str | None) -> int | None:
        try:
            value = round(float(self._state(entity_id)))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _readings(self, system: DetectedSystem) -> list[Reading]:
        mods = [self._kwh(r.get("module_rated_capacity")) for r in system.modules.values()]
        if mods and all(k for k in mods):
            # One reading per module: modules of different models are each recognised.
            return [Reading(module_kwh=[k]) for k in mods]
        readings = []
        for roles in system.inverters.values():
            rated = self._kwh((roles.get("inverter_rated_capacity") or [None])[0])
            if rated is None:
                continue
            count = self._int((roles.get("inverter_pack_count") or [None])[0])
            if count is None and roles.get("pack_serial"):
                count = sum(1 for e in roles["pack_serial"] if (self._state(e) or "") not in _NO_VALUE) or None
            model = self._state((roles.get("inverter_model") or [None])[0])
            readings.append(Reading(rated_kwh=rated, count=count, model_text=model))
        if readings:
            return readings
        rated = self._kwh(system.roles.get("rated_capacity", (None, None))[1])
        if rated is None:
            return []
        modules = self._int(system.roles.get("module_count", (None, None))[1])
        towers = self._int(system.roles.get("tower_count", (None, None))[1])
        if towers and modules:
            return [Reading(rated_kwh=rated / towers, count=modules) for _ in range(towers)]
        return [Reading(rated_kwh=rated, count=modules)]

    def _brands(self, profile: dict, system: DetectedSystem) -> list[str]:
        """The profile's brands, narrowed by a brand entity (e.g. Energy Manager's inverter brand)."""
        brands = list(profile["brands"])
        if "brand" in system.roles:
            state = self._state(system.roles["brand"][1])
            values = next((r.get("values", {}) for r in profile["roles"]["brand"]), {})
            if state in values:
                brands = [b for b in values[state] if b in brands] or brands
        return brands

    async def async_step_detect_result(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        profile = next((p for p in index.profiles if self._system and p["id"] == self._system.profile_id), None)
        if self._system is None or profile is None:
            # Nothing chosen (or its profile left the Store list): look the battery up instead.
            return await self.async_step_store_search()
        # Detection ran over every entity, enabled or not; refresh it now the chosen ones may be on.
        refreshed = [s for s in detect(profile, _registry_entities(self.hass)) if s.key == self._system.key]
        if refreshed:
            self._system = refreshed[0]
        brands = self._brands(profile, self._system)
        specs = [s for s in index.specs if s["brand"] in brands]
        result = suggest(specs, self._readings(self._system))
        if result.decided:
            self._queue = [spec for spec, _ in result.groups]
            self._queue_units = [units for _, units in result.groups]
            return await self.async_step_group()
        if result.candidates:
            self._matches = result.candidates
            self._suggested_units = result.units
            return await self.async_step_store_select()
        if len(brands) == 1:
            self._filters["brand"] = brands[0]
        return await self.async_step_store_search()

    # --- Store search ----------------------------------------------------------

    async def async_step_store_search(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        errors: dict[str, str] = {}
        if user_input is not None:
            self._filters = {
                "search": user_input.get("search", "").strip(),
                "brand": user_input.get("brand") or ANY,
                "series": ANY,
                "region": user_input.get("region") or ANY,
                "phase": user_input.get("phase") or ANY,
            }
            self._matches = index.search(self._filters["search"], self._filters["brand"],
                                         self._filters["region"], self._filters["phase"])
            if self._matches:
                # Model is its own step so its list only holds models of the chosen brand (and other
                # filters): a form can't refresh one dropdown when another changes.
                if len(_models_in(self._matches)) > 1:
                    return await self.async_step_store_model()
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

    async def async_step_store_model(self, user_input: dict | None = None) -> ConfigFlowResult:
        models = _models_in(self._matches)
        if user_input is not None:
            chosen = user_input.get("series")
            if chosen:
                self._filters["series"] = chosen
                self._matches = [s for s in self._matches if f"{s['brand']}|{s.get('series', '')}" == chosen]
            return await self.async_step_store_select()
        one_brand = len({b for b, _ in models}) == 1
        options = [sel.SelectOptionDict(value=f"{b}|{sr}", label=sr if one_brand else f"{sr} ({b})")
                   for b, sr in models]
        return self.async_show_form(
            step_id="store_model",
            data_schema=vol.Schema({vol.Optional("series"): sel.SelectSelector(
                sel.SelectSelectorConfig(options=options, mode=sel.SelectSelectorMode.LIST))}),
            description_placeholders={"matches": str(len(self._matches)), "models": str(len(models))},
        )

    async def async_step_store_select(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            chosen = user_input.get("spec_ids") or []
            if chosen:
                self._queue = [s for s in self._matches if s["id"] in chosen]
                self._queue_units = [self._suggested_units.get(s["id"]) for s in self._queue]
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
                self._queue_units = [None]
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
            self._pending_units = self._queue_units.pop(0) if self._queue_units else None
        spec = self._pending_spec
        errors: dict[str, str] = {}
        placeholders = {**_spec_summary(spec), "remaining": str(len(self._queue)),
                        "allowed": _allowed_units(spec), **_currency_placeholders(self.hass.config.currency)}
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
                group = {CONF_SPEC: spec, CONF_UNITS: units, CONF_INSTALL_DATE: install.isoformat()}
                if user_input.get(CONF_COST):
                    group[CONF_COST] = float(user_input[CONF_COST])
                self._groups.append(group)
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
            vol.Optional(CONF_COST): _cost_box(),
        })
        if user_input is not None:
            suggested = user_input
        else:
            suggested = {k: v for k, v in (await self._group_prefill(spec)).items() if v is not None}
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)
        return self.async_show_form(step_id="group", data_schema=schema, errors=errors,
                                    description_placeholders=placeholders)

    async def _group_prefill(self, spec: dict) -> dict[str, Any]:
        return await _async_group_prefill(self.hass, spec, len(self._groups), self._pending_units)

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

        entities = _registry_entities(self.hass)
        self._detected = {}
        per_profile: dict[str, list[DetectedSystem]] = {}
        for profile in profiles:
            # Only systems with sensors to fill in (per-inverter readings alone are for suggestions).
            found = [s for s in detect(profile, entities) if s.roles or s.modules]
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
        if self._system and self._system.value in self._detected:
            default = self._system.value  # the system chosen when detecting
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

    async def async_step_modules(self, user_input: dict | None = None) -> ConfigFlowResult:
        if self._system is None:
            return await self.async_step_system()
        mods = {mid: roles for mid, roles in self._system.modules.items() if "module_discharged_energy" in roles}
        rated = {mid: _read_float(self.hass, r.get("module_rated_capacity")) for mid, r in mods.items()}
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
            for g, (found, want) in zip(self._groups, counts, strict=True))
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


def _group_label(g: dict) -> str:
    """Data only: '6 × Sigenergy SigenStor BAT 8.0 · 2025-07-18'."""
    return f"{g[CONF_UNITS]} × {g[CONF_SPEC]['brand']} {g[CONF_SPEC]['model']} · {g[CONF_INSTALL_DATE]}"


def _check_group(spec: dict, units: int, install: date) -> dict[str, str]:
    errors: dict[str, str] = {}
    try:
        validate_units(spec, units)
    except SpecError:
        errors[CONF_UNITS] = "bad_units"
    if install > dt_util.now().date():
        errors[CONF_INSTALL_DATE] = "future_date"
    return errors


class BatteryLedgerOptionsFlow(OptionsFlow):
    """Change sensors, currency style, battery groups and each group's cost after setup."""

    def __init__(self) -> None:
        self._cost_index = 0
        self._costs: list[float | None] = []
        self._edit_index: int | None = None
        self._add_spec: dict | None = None
        self._pending_groups: list[dict] = []
        self._module_target = 0
        self._new_modules: dict[str, dict] = {}

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["system", "groups", "costs"])

    # --- Battery groups: change units / warranty start, remove, or add one --------------------

    def _save_groups(self, groups: list[dict], modules: list[dict] | None = None) -> ConfigFlowResult:
        """Store the groups (and module assignments) with the entry; the reload recalculates everything."""
        data = {**self.config_entry.data, CONF_GROUPS: groups}
        if modules is not None:
            data[CONF_MODULES] = modules
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def _async_new_modules(self) -> dict[str, dict]:
        """Battery modules the setup's integration now reports that aren't tracked yet (e.g. modules added to a
        stack), when this setup tracks modules individually. Module ID -> its roles."""
        data = self.config_entry.data
        tracked = {m.get(MOD_DISCHARGED) for m in data.get(CONF_MODULES) or []} - {None}
        if not tracked or not data.get(CONF_PROFILE):
            return {}
        index = await async_get_store_index(self.hass)
        profile = next((p for p in index.profiles if p["id"] == data[CONF_PROFILE]), None)
        if profile is None:
            return {}
        for system in detect(profile, _registry_entities(self.hass)):
            mods = {mid: r for mid, r in system.modules.items() if "module_discharged_energy" in r}
            if tracked & {r["module_discharged_energy"] for r in mods.values()}:  # the system this setup tracks
                return {mid: r for mid, r in mods.items() if r["module_discharged_energy"] not in tracked}
        return {}

    async def _async_finish_groups(self, groups: list[dict], target: int) -> ConfigFlowResult:
        """Save, first offering any untracked battery modules to the added or enlarged group."""
        self._new_modules = await self._async_new_modules()
        if not self._new_modules:
            return self._save_groups(groups)
        self._pending_groups, self._module_target = groups, target
        return await self.async_step_group_modules()

    async def async_step_group_modules(self, user_input: dict | None = None) -> ConfigFlowResult:
        groups, target = self._pending_groups, self._module_target
        spec = groups[target][CONF_SPEC]
        rated = {mid: _read_float(self.hass, r.get("module_rated_capacity")) for mid, r in self._new_modules.items()}
        cap = spec["capacity"].get("reported_kwh", spec["capacity"].get("nominal_kwh"))
        # Only modules matching this group's battery model (by rated capacity) can join it
        fits = {mid for mid, kwh in rated.items() if kwh is not None and cap and abs(kwh - cap) <= cap * 0.03}
        existing = [m for m in self.config_entry.data.get(CONF_MODULES) or [] if int(m[MOD_GROUP]) == target]
        found, want = len(existing) + len(fits), groups[target][CONF_UNITS]
        if user_input is not None:
            modules = list(self.config_entry.data.get(CONF_MODULES) or [])
            if user_input[CONF_USE_MODULES]:
                modules += [{MOD_ID: mid, MOD_GROUP: target,
                             MOD_DISCHARGED: self._new_modules[mid]["module_discharged_energy"],
                             MOD_SOC: self._new_modules[mid].get("module_soc")} for mid in sorted(fits)]
            return self._save_groups(groups, modules)
        lines = [f"- {mid}: {f'{_num(rated[mid])} kWh' if rated[mid] is not None else '?'} {'✓' if mid in fits else '✗'}"
                 for mid in sorted(self._new_modules)]
        return self.async_show_form(
            step_id="group_modules",
            data_schema=vol.Schema({vol.Required(CONF_USE_MODULES, default=bool(fits) and found == want):
                                    sel.BooleanSelector()}),
            description_placeholders={"count": str(len(self._new_modules)), "modules": "\n".join(lines),
                                      "model": spec["model"], "found": str(found), "units": str(want)})

    async def async_step_groups(self, user_input: dict | None = None) -> ConfigFlowResult:
        groups = self.config_entry.data[CONF_GROUPS]
        return self.async_show_menu(step_id="groups", menu_options=["group_pick", "group_add"],
                                    description_placeholders={"groups": "\n".join(f"- {_group_label(g)}" for g in groups)})

    async def async_step_group_pick(self, user_input: dict | None = None) -> ConfigFlowResult:
        groups = self.config_entry.data[CONF_GROUPS]
        if user_input is not None:
            self._edit_index = int(user_input["group"])
            return await self.async_step_group_edit()
        if len(groups) == 1:
            self._edit_index = 0
            return await self.async_step_group_edit()
        options = [sel.SelectOptionDict(value=str(i), label=_group_label(g)) for i, g in enumerate(groups)]
        return self.async_show_form(step_id="group_pick", data_schema=vol.Schema({
            vol.Required("group", default="0"): sel.SelectSelector(
                sel.SelectSelectorConfig(options=options, mode=sel.SelectSelectorMode.LIST)),
        }))

    async def async_step_group_edit(self, user_input: dict | None = None) -> ConfigFlowResult:
        groups = [dict(g) for g in self.config_entry.data[CONF_GROUPS]]
        i = self._edit_index or 0
        g = groups[i]
        spec = g[CONF_SPEC]
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("remove"):
                if len(groups) == 1:
                    errors["base"] = "last_group"
                else:
                    # Drop the group and its modules; modules of later groups move down one place.
                    del groups[i]
                    modules = []
                    for m in self.config_entry.data.get(CONF_MODULES) or []:
                        grp = int(m[MOD_GROUP])
                        if grp != i:
                            modules.append({**m, MOD_GROUP: grp - 1 if grp > i else grp})
                    return self._save_groups(groups, modules)
            else:
                units = int(user_input[CONF_UNITS])
                install = date.fromisoformat(user_input[CONF_INSTALL_DATE])
                errors = _check_group(spec, units, install)
                if not errors:
                    groups[i] = {**g, CONF_UNITS: units, CONF_INSTALL_DATE: install.isoformat()}
                    if units > g[CONF_UNITS]:  # modules added to this group: offer any new module sensors
                        return await self._async_finish_groups(groups, i)
                    return self._save_groups(groups)
        cap = spec["capacity"]
        schema = vol.Schema({
            vol.Required(CONF_UNITS): _num_box(min=cap.get("min_units", 1),
                                               max=cap.get("max_units", 100 if cap["unit"] == "module" else 20), step=1),
            vol.Required(CONF_INSTALL_DATE): sel.DateSelector(),
            vol.Optional("remove", default=False): sel.BooleanSelector(),
        })
        schema = self.add_suggested_values_to_schema(
            schema, user_input or {CONF_UNITS: g[CONF_UNITS], CONF_INSTALL_DATE: g[CONF_INSTALL_DATE]})
        return self.async_show_form(step_id="group_edit", data_schema=schema, errors=errors,
                                    description_placeholders={**_spec_summary(spec), "allowed": _allowed_units(spec),
                                                              "number": str(i + 1), "total": str(len(groups))})

    async def async_step_group_add(self, user_input: dict | None = None) -> ConfigFlowResult:
        index = await async_get_store_index(self.hass)
        await index.async_refresh_if_stale()
        if user_input is not None:
            self._add_spec = index.get(user_input[CONF_SPEC])
            if self._add_spec is not None:
                return await self.async_step_group_add_details()
        # The setup's brands first (e.g. a second stack of the same battery), then the rest of the Store
        mine = {g[CONF_SPEC]["brand"] for g in self.config_entry.data[CONF_GROUPS]}
        specs = sorted(index.specs, key=lambda sp: sp["brand"] not in mine)
        options = [sel.SelectOptionDict(value=sp["id"], label=spec_label(sp)) for sp in specs]
        return self.async_show_form(step_id="group_add", data_schema=vol.Schema({
            vol.Required(CONF_SPEC): sel.SelectSelector(
                sel.SelectSelectorConfig(options=options, mode=sel.SelectSelectorMode.DROPDOWN)),
        }))

    async def async_step_group_add_details(self, user_input: dict | None = None) -> ConfigFlowResult:
        spec = self._add_spec
        if spec is None:
            return await self.async_step_group_add()
        groups = [dict(g) for g in self.config_entry.data[CONF_GROUPS]]
        errors: dict[str, str] = {}
        if user_input is not None:
            units = int(user_input[CONF_UNITS])
            install = date.fromisoformat(user_input[CONF_INSTALL_DATE])
            errors = _check_group(spec, units, install)
            if not errors:
                group = {CONF_SPEC: spec, CONF_UNITS: units, CONF_INSTALL_DATE: install.isoformat()}
                if user_input.get(CONF_COST):
                    group[CONF_COST] = float(user_input[CONF_COST])
                return await self._async_finish_groups([*groups, group], len(groups))
        cap = spec["capacity"]
        schema = vol.Schema({
            vol.Required(CONF_UNITS, default=cap.get("min_units", 1)): _num_box(
                min=cap.get("min_units", 1), max=cap.get("max_units", 100 if cap["unit"] == "module" else 20), step=1),
            vol.Required(CONF_INSTALL_DATE): sel.DateSelector(),
            vol.Optional(CONF_COST): _cost_box(),
        })
        # Batteries added later: e.g. Energy Manager's battery_install_date_2 / battery_install_cost_2
        suggested = user_input or {k: v for k, v in (await _async_group_prefill(self.hass, spec, len(groups))).items()
                                   if v is not None}
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)
        code = self.config_entry.data.get(CONF_CURRENCY) or self.hass.config.currency
        return self.async_show_form(step_id="group_add_details", data_schema=schema, errors=errors,
                                    description_placeholders={**_spec_summary(spec), "allowed": _allowed_units(spec),
                                                              **_currency_placeholders(code)})

    async def async_step_system(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_system(user_input)
            if not errors:
                # Store every field so a cleared optional field overrides setup data.
                data = {k: user_input.get(k) for k in
                        (CONF_CURRENCY_STYLE, CONF_CHARGED_ENTITY, CONF_DISCHARGED_ENTITY,
                         CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY)}
                return self.async_create_entry(data=data)
        current = {**self.config_entry.data, **self.config_entry.options}
        schema = _system_schema({CONF_CURRENCY_STYLE: current.get(CONF_CURRENCY_STYLE, CURRENCY_STYLE_CODE)},
                                with_name=False)
        schema = self.add_suggested_values_to_schema(schema, user_input or current)
        code = current.get(CONF_CURRENCY) or self.hass.config.currency
        return self.async_show_form(step_id="system", data_schema=schema, errors=errors,
                                    description_placeholders=_currency_placeholders(code))

    async def async_step_costs(self, user_input: dict | None = None) -> ConfigFlowResult:
        """One form per battery group; the costs are saved with the groups when the last is done."""
        groups = self.config_entry.data[CONF_GROUPS]
        if user_input is not None:
            self._costs.append(float(user_input[CONF_COST]) if user_input.get(CONF_COST) else None)
            self._cost_index += 1
            if self._cost_index >= len(groups):
                new_groups = []
                for g, cost in zip(groups, self._costs, strict=True):
                    g = {k: v for k, v in g.items() if k != CONF_COST}
                    if cost:
                        g[CONF_COST] = cost
                    new_groups.append(g)
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={**self.config_entry.data, CONF_GROUPS: new_groups})
                return self.async_create_entry(data=dict(self.config_entry.options))
        g = groups[self._cost_index]
        schema = vol.Schema({vol.Optional(CONF_COST): _cost_box()})
        if g.get(CONF_COST):
            schema = self.add_suggested_values_to_schema(schema, {CONF_COST: g[CONF_COST]})
        code = self.config_entry.data.get(CONF_CURRENCY) or self.hass.config.currency
        return self.async_show_form(step_id="costs", data_schema=schema, description_placeholders={
            "group": f"{g[CONF_UNITS]} × {g[CONF_SPEC]['brand']} {g[CONF_SPEC]['model']}",
            "install_date": g[CONF_INSTALL_DATE],
            "number": str(self._cost_index + 1), "total": str(len(groups)),
            **_currency_placeholders(code),
        })
