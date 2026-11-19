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
    kept = reg.async_get(renamed.entity_id)
    assert kept.entity_id == "sensor.my_custom_health"
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


async def test_1_3_cost_moves_to_first_group(hass: HomeAssistant):
    """1.3 -> 1.4: the setup's cost becomes the first battery group's cost; nothing else changes."""
    second = {**V1_DATA["groups"][0], "units": 1, "install_date": "2026-01-01"}
    data = {**V1_DATA, "groups": [V1_DATA["groups"][0], second], "currency_style": "code", "cost": 9000}
    entry = MockConfigEntry(domain=DOMAIN, title="Acme", data=data, version=1, minor_version=3)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (entry.version, entry.minor_version) == (CONFIG_ENTRY_VERSION, CONFIG_ENTRY_MINOR_VERSION)
    assert "cost" not in entry.data
    assert entry.data["groups"][0] == {**V1_DATA["groups"][0], "cost": 9000}
    assert entry.data["groups"][1] == second  # a later group has no cost until the user adds one
    assert {k: v for k, v in entry.data.items() if k != "groups"} == {
        k: v for k, v in data.items() if k not in ("groups", "cost")}


async def test_1_3_options_cost_wins(hass: HomeAssistant):
    """1.3 -> 1.4: a cost changed in the options (which overrode setup data) is the one kept."""
    data = {**V1_DATA, "currency_style": "code", "cost": 9000}
    entry = MockConfigEntry(domain=DOMAIN, title="Acme", data=data, options={"cost": 9500, "currency_style": "symbol"},
                            version=1, minor_version=3)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data["groups"][0]["cost"] == 9500
    assert "cost" not in entry.data and "cost" not in entry.options
    assert entry.options == {"currency_style": "symbol", "esl_years": None, "export_cost_basis": "warranty"}


async def test_1_3_cleared_cost_and_no_cost(hass: HomeAssistant):
    """1.3 -> 1.4: a cost cleared in the options (None) or never entered leaves the group without one."""
    for options in ({"cost": None}, {}):
        entry = MockConfigEntry(domain=DOMAIN, title="Acme", data={**V1_DATA, "cost": 9000} if options else V1_DATA,
                                options=options, version=1, minor_version=3)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert "cost" not in entry.data["groups"][0]
        assert "cost" not in entry.data and "cost" not in entry.options


async def test_1_4_adds_service_life_options(hass: HomeAssistant):
    """1.4 -> 1.5: Estimated Service Life unset (= warranty period) and the warranty export basis."""
    entry = MockConfigEntry(domain=DOMAIN, title="Acme", data=V1_DATA, options={"currency_style": "code"},
                            version=1, minor_version=4)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (entry.version, entry.minor_version) == (1, 5)
    assert entry.options == {"currency_style": "code", "esl_years": None, "export_cost_basis": "warranty"}
    # Idempotent: a second run changes nothing
    from custom_components.battery_ledger import async_migrate_entry
    assert await async_migrate_entry(hass, entry)
    assert entry.options == {"currency_style": "code", "esl_years": None, "export_cost_basis": "warranty"}
