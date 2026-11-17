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
