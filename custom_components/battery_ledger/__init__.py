"""BatteryLedger: battery warranty, degradation and cost tracking for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CURRENCY_STYLE,
    CONF_COST,
    CONF_GROUPS,
    CURRENCY_STYLE_CODE,
    CONF_SPEC,
    CONF_ESL_YEARS,
    CONF_EXPORT_SETTING,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    ENTITY_ID_PREFIX,
    MANUAL_ID_PREFIX,
    REMOVED_SENSOR_KEYS_1_3,
    SENSOR_KEY_RENAMES_1_2,
    STORE_REFRESH_INTERVAL,
)
from .card import async_register_card, async_remove_card_settings
from .runtime import CAPACITY_STORE_VERSION, LedgerRuntime, capacity_store_key
from .store_client import StoreIndex, async_get_store_index

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NUMBER, Platform.SELECT, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type BatteryLedgerConfigEntry = ConfigEntry[LedgerRuntime]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Load the BatteryLedger dashboard card in the frontend."""
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BatteryLedgerConfigEntry) -> bool:
    index = await async_get_store_index(hass)
    _ensure_store_refresh(hass, index)

    runtime = LedgerRuntime(hass, entry)
    await runtime.async_load()
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.async_start()
    entry.async_on_unload(runtime.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    check_spec_updates(hass, index, entry)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an entry saved by an older BatteryLedger up to the current format.

    Rules: deterministic and idempotent, never drop user data (groups, specs, install
    dates, cost, sensor choices), one step per version, each with an old-format test.
    """
    if entry.version > CONFIG_ENTRY_VERSION:
        # Saved by a newer BatteryLedger: refuse rather than guess (user downgraded).
        _LOGGER.error("BatteryLedger entry '%s' is version %s.%s, newer than this release supports (%s.%s)",
                      entry.title, entry.version, entry.minor_version,
                      CONFIG_ENTRY_VERSION, CONFIG_ENTRY_MINOR_VERSION)
        return False

    data = {**entry.data}
    version, minor = entry.version, entry.minor_version

    if version == 1 and minor < 2:
        await _migrate_entities_1_2(hass, entry)
        minor = 2

    if version == 1 and minor < 3:
        # 0.1.3 (entry 1.3): currency comes from Home Assistant's regional setting, with a code/symbol choice.
        # A currency typed into an older setup is kept (and still used); the display stays as code.
        data.setdefault(CONF_CURRENCY_STYLE, CURRENCY_STYLE_CODE)
        # Sensors that duplicated the YAML package's attributes are gone; remove their registry entries.
        registry = er.async_get(hass)
        for key in REMOVED_SENSOR_KEYS_1_3:
            if entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}"):
                registry.async_remove(entity_id)
        minor = 3

    options = {**entry.options}
    if version == 1 and minor < 4:
        # 0.1.6 (entry 1.4): cost belongs to each battery group, so batteries added later can carry
        # their own. The setup's cost (the options value wins, as it did at runtime) goes to the first group.
        cost = options.pop(CONF_COST) if CONF_COST in options else data.pop(CONF_COST, None)
        data.pop(CONF_COST, None)
        groups = [dict(g) for g in data.get(CONF_GROUPS, [])]
        if groups and cost is not None and CONF_COST not in groups[0]:
            groups[0][CONF_COST] = cost
        data[CONF_GROUPS] = groups
        minor = 4

    if version == 1 and minor < 5:
        # 0.1.16 (entry 1.5): Estimated Service Life (None = the default, 15 years from 0.1.18) and the export cost
        # basis (warranty, as v0.1.16 published) are options that change without a reload.
        options.setdefault(CONF_ESL_YEARS, None)
        options.setdefault(CONF_EXPORT_SETTING, "warranty")
        minor = 5

    if version == 1 and minor < 6:
        # 0.2.0 (entry 1.6): an optional battery state of charge sensor (soc_entity; absent = none), for measured
        # usable capacity. Nothing to change in stored data.
        minor = 6
    if version == 1 and minor < 7:
        # 0.3.0 (entry 1.7): optional battery towers (towers; absent = none) and pack SoH sensors
        # (pack_soh_entities; absent = none). Nothing to change in stored data.
        minor = 7

    # Future steps go here, oldest first.

    if (version, minor) != (entry.version, entry.minor_version):
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=version,
                                               minor_version=minor)
        _LOGGER.info("Migrated BatteryLedger entry '%s' to version %s.%s", entry.title, version, minor)
    return True


async def _migrate_entities_1_2(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """0.1.1 -> 0.1.2: sensor keys and entity IDs back to the original YAML package's names.

    Unique IDs always move to the new key (so history stays with the entity). The entity ID
    moves to sensor.battery_ledger_<key> only if the user hadn't renamed it and the new ID is free.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"

    @callback
    def _update(entity: er.RegistryEntry) -> dict | None:
        if entity.domain != "sensor" or not entity.unique_id.startswith(prefix):
            return None
        old_key = entity.unique_id[len(prefix):]
        if old_key not in SENSOR_KEY_RENAMES_1_2:
            return None
        new_key, old_suffix = SENSOR_KEY_RENAMES_1_2[old_key]
        changes: dict = {}
        if new_key != old_key:
            changes["new_unique_id"] = f"{prefix}{new_key}"
        new_entity_id = f"sensor.{ENTITY_ID_PREFIX}_{new_key}"
        if (entity.entity_id.endswith(f"_{old_suffix}") and entity.entity_id != new_entity_id
                and registry.async_get(new_entity_id) is None):
            changes["new_entity_id"] = new_entity_id
        return changes or None

    await er.async_migrate_entries(hass, entry.entry_id, _update)


async def async_unload_entry(hass: HomeAssistant, entry: BatteryLedgerConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_save_capacity()
        remaining = [e for e in _loaded_entries(hass) if e.entry_id != entry.entry_id]
        if not remaining:
            unsub = hass.data.get(DOMAIN, {}).pop("refresh_unsub", None)
            if unsub:
                unsub()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    for issue_id in _issue_ids_for(hass, entry.entry_id):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    await async_remove_card_settings(hass, entry.entry_id)
    await Store(hass, CAPACITY_STORE_VERSION, capacity_store_key(entry.entry_id)).async_remove()


def _loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and runtime.only_live_options_changed():
        # ESL / export basis (number and select entities): recalculate, no reload
        runtime.remember_entry()
        runtime.recalculate()
        return
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _ensure_store_refresh(hass: HomeAssistant, index: StoreIndex) -> None:
    """One daily Store refresh shared by all entries; afterwards look for revised specs."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "refresh_unsub" in domain_data:
        return

    async def _refresh(_now=None) -> None:
        await index.async_refresh_if_stale()
        for entry in _loaded_entries(hass):
            check_spec_updates(hass, index, entry)

    domain_data["refresh_unsub"] = async_track_time_interval(hass, _refresh, STORE_REFRESH_INTERVAL)
    hass.async_create_background_task(_refresh(), f"{DOMAIN} store refresh")


def _issue_id(entry_id: str, spec_id: str) -> str:
    return f"spec_updated_{entry_id}_{spec_id}"


def _issue_ids_for(hass: HomeAssistant, entry_id: str) -> list[str]:
    reg = ir.async_get(hass)
    prefix = f"spec_updated_{entry_id}_"
    return [iid for (domain, iid) in reg.issues if domain == DOMAIN and iid.startswith(prefix)]


@callback
def check_spec_updates(hass: HomeAssistant, index: StoreIndex, entry: ConfigEntry) -> None:
    """Raise a fixable repair when the Store has a newer version of a spec in use.

    Specs are copied into the entry when chosen, so a Store change never silently
    alters an existing setup's figures; the user reviews and accepts it.
    """
    wanted: set[str] = set()
    for group in entry.data.get(CONF_GROUPS, []):
        spec = group[CONF_SPEC]
        if spec["id"].startswith(MANUAL_ID_PREFIX):
            continue
        latest = index.get(spec["id"])
        if latest is None or latest.get("spec_version", 0) <= spec.get("spec_version", 0):
            continue
        issue_id = _issue_id(entry.entry_id, spec["id"])
        wanted.add(issue_id)
        ir.async_create_issue(
            hass, DOMAIN, issue_id,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="spec_updated",
            translation_placeholders={
                "entry": entry.title,
                "model": f"{spec['brand']} {spec['model']}",
                "old": str(spec.get("spec_version")),
                "new": str(latest.get("spec_version")),
            },
            data={"entry_id": entry.entry_id, "spec_id": spec["id"]},
        )
    for issue_id in _issue_ids_for(hass, entry.entry_id):
        if issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
