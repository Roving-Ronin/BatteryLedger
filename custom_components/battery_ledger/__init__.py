"""BatteryLedger: battery warranty, degradation and cost tracking for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_GROUPS,
    CONF_SPEC,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    MANUAL_ID_PREFIX,
    STORE_REFRESH_INTERVAL,
)
from .runtime import LedgerRuntime
from .store_client import StoreIndex, async_get_store_index

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

type BatteryLedgerConfigEntry = ConfigEntry[LedgerRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: BatteryLedgerConfigEntry) -> bool:
    index = await async_get_store_index(hass)
    _ensure_store_refresh(hass, index)

    runtime = LedgerRuntime(hass, entry)
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

    # Future steps go here, oldest first, e.g.:
    # if version == 1 and minor < 2:
    #     data = _migrate_1_1_to_1_2(data)
    #     minor = 2

    if (version, minor) != (entry.version, entry.minor_version):
        hass.config_entries.async_update_entry(entry, data=data, version=version, minor_version=minor)
        _LOGGER.info("Migrated BatteryLedger entry '%s' to version %s.%s", entry.title, version, minor)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BatteryLedgerConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        remaining = [e for e in _loaded_entries(hass) if e.entry_id != entry.entry_id]
        if not remaining:
            unsub = hass.data.get(DOMAIN, {}).pop("refresh_unsub", None)
            if unsub:
                unsub()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    for issue_id in _issue_ids_for(hass, entry.entry_id):
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
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
