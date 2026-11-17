"""Config entry migration. Each future migration step gets an old-format test here."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.battery_ledger.const import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION, DOMAIN

V1_DATA = {
    "groups": [{
        "spec": {"id": "custom-acme-x", "brand": "Acme", "model": "X", "spec_version": 0, "regions": ["AU"],
                 "phases": ["1"], "chemistry": "LFP",
                 "capacity": {"unit": "module", "usable_kwh": 5.0},
                 "warranty": {"years": 10, "eol_capacity_pct": 70,
                              "throughput": {"basis": "charged", "scope": "per_unit", "kwh": 15000}}},
        "units": 2, "install_date": "2025-01-01"}],
    "charged_energy_entity": "sensor.charged",
    "currency": "AUD",
}


async def test_current_version_loads_unchanged(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, title="Acme", data=V1_DATA,
                            version=CONFIG_ENTRY_VERSION, minor_version=CONFIG_ENTRY_MINOR_VERSION)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == V1_DATA


async def test_newer_version_is_refused(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, title="Acme", data=V1_DATA, version=CONFIG_ENTRY_VERSION + 1)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.data == V1_DATA  # never modified


async def test_0_1_1_entities_renamed(hass: HomeAssistant):
    """1.1 -> 1.2: v0.1.1 sensor keys and entity IDs move to the original YAML names."""
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(domain=DOMAIN, title="Sigen battery", data=V1_DATA, version=1, minor_version=1)
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    old = reg.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_throughput_limit",
                                  suggested_object_id="sigen_battery_warranted_throughput", config_entry=entry)
    renamed = reg.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_warranty_floor_pct",
                                      suggested_object_id="my_custom_health", config_entry=entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (entry.version, entry.minor_version) == (CONFIG_ENTRY_VERSION, CONFIG_ENTRY_MINOR_VERSION)

    moved = reg.async_get(old.entity_id) or reg.async_get("sensor.battery_ledger_total_rated_throughput")
    assert moved.entity_id == "sensor.battery_ledger_total_rated_throughput"
    assert moved.unique_id == f"{entry.entry_id}_total_rated_throughput"
    # A user-renamed entity keeps its entity ID; only its unique ID moves.
    kept = reg.async_get("sensor.my_custom_health")
    assert kept.unique_id == f"{entry.entry_id}_estimated_usable_capacity"
    assert entry.data == V1_DATA
