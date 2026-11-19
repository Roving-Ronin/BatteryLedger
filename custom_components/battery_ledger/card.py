"""Serves the BatteryLedger dashboard card, loads it in the frontend, and gives it its data.

The card ships with the integration, so it updates with each release and needs no separate install
or dashboard resource. The URL carries the integration version so browsers fetch the new file after
an update instead of a cached one.

Websocket commands:
- ``battery_ledger/card/setups``: every loaded setup, with its sensors' entity IDs (found by unique ID,
  so renamed entities still work), its battery groups and the card settings saved for it.
- ``battery_ledger/card/save_settings`` (admins): the settings chosen in the card's settings window.
  They're kept per setup, so every dashboard and device shows that setup's card the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .backup import ExportView, async_export_link
from .const import CONF_GROUPS, CONF_INSTALL_DATE, CONF_PROFILE, CONF_SOH_ENTITY, CONF_SPEC, CONF_UNITS, DOMAIN
from .store_client import StoreIndex, async_get_store_index

CARD_FILE = Path(__file__).parent / "www" / "battery-ledger-card.js"
CARD_URL = f"/{DOMAIN}/battery-ledger-card.js"
LOGO_FILE = Path(__file__).parent / "www" / "battery-ledger-logo.png"
LOGO_URL = f"/{DOMAIN}/battery-ledger-logo.png"
_REGISTERED = f"{DOMAIN}_card_registered"
_SETTINGS = f"{DOMAIN}_card_settings"
SETTINGS_STORE_KEY = f"{DOMAIN}.card_settings"

SECTIONS = ("warranty", "throughput", "cost", "health")
# How the card shows dates: the user's Home Assistant date format, or day, month name, year (18 Jul 2035).
DATE_STYLES = ("ha", "day_month_year")
DEFAULT_SETTINGS: dict[str, Any] = {"cost_decimals": 4, "date_style": "ha", "sections": {s: True for s in SECTIONS}}

# Sensor keys the card reads (unique ID = "<entry_id>_<key>").
CARD_SENSOR_KEYS = (
    "total_rated_throughput", "remaining_rated_throughput", "projected_warranted_throughput",
    "rated_throughput_used", "warranty_time_elapsed", "cycles_per_day",
    "cost_per_kwh_rated", "cost_per_kwh_projected", "cost_consumed_to_date",
    "initial_usable_capacity", "estimated_usable_capacity", "soh_above_warranty_floor",
    "hardware_capacity_validation", "most_used_module_throughput", "module_soc_spread",
)

SETTINGS_SCHEMA = vol.Schema({
    vol.Required("cost_decimals"): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
    vol.Optional("date_style"): vol.In(DATE_STYLES),
    vol.Required("sections"): {vol.In(SECTIONS): bool},
})


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card file, add it to every frontend page and register its commands (once per start)."""
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    websocket_api.async_register_command(hass, ws_setups)
    websocket_api.async_register_command(hass, ws_save_settings)
    websocket_api.async_register_command(hass, ws_export_link)
    if hass.http is None:  # no web server (e.g. some test setups)
        return
    hass.http.register_view(ExportView())
    await hass.http.async_register_static_paths([
        StaticPathConfig(CARD_URL, str(CARD_FILE), True),
        StaticPathConfig(LOGO_URL, str(LOGO_FILE), True),
    ])
    if DATA_EXTRA_MODULE_URL in hass.data:  # the frontend is loaded
        version = (await async_get_integration(hass, DOMAIN)).version
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")


async def _settings_store(hass: HomeAssistant) -> tuple[Store, dict[str, dict]]:
    if _SETTINGS not in hass.data:
        store: Store = Store(hass, 1, SETTINGS_STORE_KEY)
        hass.data[_SETTINGS] = (store, await store.async_load() or {})
    return hass.data[_SETTINGS]


async def async_card_settings(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """One setup's card settings, with defaults (for the setup file)."""
    _store, settings = await _settings_store(hass)
    return _with_defaults(settings.get(entry_id))


async def async_restore_card_settings(hass: HomeAssistant, entry_id: str, saved: dict | None) -> None:
    """Card settings from an imported setup file, if they're valid."""
    if not saved:
        return
    try:
        checked = SETTINGS_SCHEMA({k: v for k, v in saved.items() if k in ("cost_decimals", "date_style", "sections")})
    except vol.Invalid:
        return
    store, settings = await _settings_store(hass)
    settings[entry_id] = _with_defaults(checked)
    await store.async_save(settings)


def _with_defaults(saved: dict | None) -> dict[str, Any]:
    saved = saved or {}
    return {
        "cost_decimals": saved.get("cost_decimals", DEFAULT_SETTINGS["cost_decimals"]),
        "date_style": saved.get("date_style", DEFAULT_SETTINGS["date_style"]),
        "sections": {**DEFAULT_SETTINGS["sections"], **saved.get("sections", {})},
    }


@callback
def _soh_source(entry, index: StoreIndex, brands: list[str]) -> dict[str, Any]:
    """Where an SoH reading would come from, so the card can say why there isn't one.

    configured: a sensor is chosen. available: the setup's integration can provide SoH for these batteries
    (True), can't (False: no SoH rule, or listed unavailable for every brand here), or is unknown (None:
    manual setup, or its profile left the Store). source: the integration's name, when known.
    """
    current = {**entry.data, **entry.options}
    profile = next((p for p in index.profiles if p["id"] == entry.data.get(CONF_PROFILE)), None)
    available = None
    if profile is not None:
        missing = set(profile.get("unavailable", {}).get("soh", []))
        available = "soh" in profile.get("roles", {}) and not (brands and set(brands) <= missing)
    return {"configured": bool(current.get(CONF_SOH_ENTITY)), "available": available,
            "source": profile["name"] if profile else None}


def _setup_info(hass: HomeAssistant, entry, settings: dict, index: StoreIndex) -> dict[str, Any]:
    registry = er.async_get(hass)
    entities = {
        key: entity_id for key in CARD_SENSOR_KEYS
        if (entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}"))
    }
    runtime = entry.runtime_data
    groups = []
    for group in entry.data.get(CONF_GROUPS, []):
        spec = group[CONF_SPEC]
        warranty = spec.get("warranty", {})
        groups.append({
            "brand": spec.get("brand"), "series": spec.get("series"), "model": spec.get("model"),
            "units": group.get(CONF_UNITS), "install_date": group.get(CONF_INSTALL_DATE),
            "warranty_years": warranty.get("years"), "eol_capacity_pct": warranty.get("eol_capacity_pct"),
        })
    return {
        "entry_id": entry.entry_id, "title": entry.title, "entities": entities, "groups": groups,
        "currency": runtime.currency, "currency_label": runtime.currency_label,
        "soh": _soh_source(entry, index, sorted({g["brand"] for g in groups if g["brand"]})),
        "settings": _with_defaults(settings.get(entry.entry_id)),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/card/setups"})
@websocket_api.async_response
async def ws_setups(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Every loaded BatteryLedger setup, for the card and its editor."""
    _, settings = await _settings_store(hass)
    index = await async_get_store_index(hass)
    setups = [_setup_info(hass, entry, settings, index) for entry in hass.config_entries.async_entries(DOMAIN)
              if entry.state is ConfigEntryState.LOADED]
    connection.send_result(msg["id"], {"setups": setups, "defaults": DEFAULT_SETTINGS})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/card/save_settings",
    vol.Required("entry_id"): str,
    vol.Required("settings"): SETTINGS_SCHEMA,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Save the card settings for one setup."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown BatteryLedger setup")
        return
    store, settings = await _settings_store(hass)
    settings[entry.entry_id] = _with_defaults(msg["settings"])
    await store.async_save(settings)
    connection.send_result(msg["id"], {"settings": settings[entry.entry_id]})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/card/export_link", vol.Required("entry_id"): str})
@websocket_api.require_admin
@callback
def ws_export_link(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """A signed link to download the setup file (the card's Backup tab)."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown BatteryLedger setup")
        return
    connection.send_result(msg["id"], {"url": async_export_link(hass, entry)})


async def async_remove_card_settings(hass: HomeAssistant, entry_id: str) -> None:
    """Forget a removed setup's card settings."""
    store, settings = await _settings_store(hass)
    if settings.pop(entry_id, None) is not None:
        await store.async_save(settings)
