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
    assert entry.data == {**V1_DATA, "currency_style": "code"}  # 1.3 step adds the display style


async def test_1_2_currency_kept_and_style_added(hass: HomeAssistant):
    """1.2 -> 1.3: a currency typed into an older setup is kept and still used; style defaults to code."""
    data = {**V1_DATA, "currency": "NZD", "cost": 1000}
    entry = MockConfigEntry(domain=DOMAIN, title="Acme", data=data, version=1, minor_version=2)
    entry.add_to_hass(hass)
    hass.config.currency = "AUD"
    hass.states.async_set("sensor.charged", "10", {"unit_of_measurement": "kWh"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == CONFIG_ENTRY_MINOR_VERSION
    assert entry.data["currency"] == "NZD" and entry.data["currency_style"] == "code"
    assert hass.states.get("sensor.battery_ledger_cost_per_kwh_rated").attributes["unit_of_measurement"] == "NZD/kWh"


async def test_1_2_duplicate_sensors_removed(hass: HomeAssistant):
    """1.2 -> 1.3: the five sensors duplicating YAML attributes are removed from the registry."""
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(domain=DOMAIN, title="Acme", data=V1_DATA, version=1, minor_version=2)
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    for key in ("degradation_driver", "warranty_status", "rated_life_used",
                "estimated_remaining_value", "remaining_usable_capacity", "total_rated_throughput"):
        reg.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_{key}",
                                suggested_object_id=f"battery_ledger_{key}", config_entry=entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert reg.async_get("sensor.battery_ledger_warranty_status") is None
    assert reg.async_get("sensor.battery_ledger_rated_life_used") is None
    assert reg.async_get("sensor.battery_ledger_total_rated_throughput") is not None  # kept
