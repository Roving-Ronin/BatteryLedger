"""End-to-end tests: config flow, sensors, Store revisions. Needs pytest-homeassistant-custom-component."""

import copy
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.battery_ledger.const import DOMAIN
from custom_components.battery_ledger.store_client import StoreIndexError, async_get_store_index

CHARGED = "sensor.sigen_plant_total_charged_energy_of_the_ess"
RATED = "sensor.sigen_plant_rated_energy_capacity"


@pytest.fixture(autouse=True)
def offline_store():
    """No network in tests: refreshes fail, so the bundled snapshot is used."""
    with patch("custom_components.battery_ledger.store_client.StoreIndex.async_refresh",
               side_effect=StoreIndexError("offline")):
        yield


async def _setup_via_flow(hass: HomeAssistant, install_date: str) -> config_entries.ConfigEntry:
    hass.config.country = "AU"
    hass.config.currency = "AUD"
    hass.states.async_set(CHARGED, "14885", {"unit_of_measurement": "kWh", "device_class": "energy"})
    hass.states.async_set(RATED, "48.36", {"unit_of_measurement": "kWh"})

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["description_placeholders"]["count"] == "4"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "store_search"})
    assert result["step_id"] == "store_search"

    # Three-phase + search text narrows to the BAT 8.0
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "bat 8", "brand": "Sigenergy", "region": "AU", "phase": "3"})
    assert result["step_id"] == "store_select"
    assert result["description_placeholders"]["matches"] == "1"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"spec_id": "sigenergy-sigenstor-bat-8-0-anz"})
    assert result["step_id"] == "store_confirm"
    assert "23.77 MWh per unit" in result["description_placeholders"]["throughput"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "group"

    with pytest.raises(InvalidData):  # selector max comes from the spec: 6 modules
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {"units": 7, "install_date": install_date})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"units": 6, "install_date": install_date})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "add_more"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "sensors"})
    assert result["step_id"] == "sensors"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"integration": "manual"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Sigen battery", "currency": "AUD"})
    assert result["errors"] == {"base": "no_energy_entity"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Sigen battery", "cost": 26062, "currency": "AUD",
         "charged_energy_entity": CHARGED, "reported_capacity_entity": RATED})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return hass.config_entries.async_get_entry(result["result"].entry_id)


async def test_flow_and_sensors(hass: HomeAssistant):
    install = (dt_util.now().date() - timedelta(days=487)).isoformat()
    entry = await _setup_via_flow(hass, install)
    assert entry.title == "Sigen battery"

    def val(object_id):
        return hass.states.get(f"sensor.sigen_battery_{object_id}")

    assert float(val("warranted_throughput").state) == 142620
    assert float(val("throughput_remaining").state) == 127735
    assert float(val("warranty_throughput_used").state) == pytest.approx(10.44, abs=0.01)
    assert float(val("cost_per_kwh_warranted").state) == pytest.approx(0.1827, abs=0.0001)
    assert val("cost_per_kwh_warranted").attributes["unit_of_measurement"] == "AUD/kWh"
    assert float(val("cost_consumed").state) == pytest.approx(2720, abs=1)
    assert val("warranty_driver").state == "age"
    assert val("warranty_status").state == "on_track"
    assert val("hardware_check").state == "match"
    assert float(val("initial_usable_capacity").state) == pytest.approx(46.8)

    # Energy counter moves -> recalculated after the debounce
    hass.states.async_set(CHARGED, "20000", {"unit_of_measurement": "kWh"})
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()
    assert float(val("throughput_used").state) == pytest.approx(20000)

    # Unavailable source -> sensors unavailable rather than wrong
    hass.states.async_set(CHARGED, "unavailable")
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()
    assert val("throughput_used").state == "unavailable"


async def test_store_revision_raises_fixable_repair(hass: HomeAssistant):
    entry = await _setup_via_flow(hass, "2025-07-18")
    index = await async_get_store_index(hass)
    revised = copy.deepcopy(index.get("sigenergy-sigenstor-bat-8-0-anz"))
    revised["spec_version"] = 2
    revised["warranty"]["throughput"]["kwh"] = 25000
    index._data["specs"] = [revised if s["id"] == revised["id"] else s for s in index.specs]

    from custom_components.battery_ledger import check_spec_updates
    check_spec_updates(hass, index, entry)
    issue_id = f"spec_updated_{entry.entry_id}_{revised['id']}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)

    from custom_components.battery_ledger.repairs import async_create_fix_flow
    flow = await async_create_fix_flow(hass, issue_id, {"entry_id": entry.entry_id, "spec_id": revised["id"]})
    flow.hass = hass
    result = await flow.async_step_init()
    assert '"kwh": 23770' in result["description_placeholders"]["changes"]
    assert '"kwh": 25000' in result["description_placeholders"]["changes"]
    await flow.async_step_confirm({})
    await hass.async_block_till_done()

    assert entry.data["groups"][0]["spec"]["spec_version"] == 2
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_manual_entry_with_table(hass: HomeAssistant):
    hass.states.async_set(CHARGED, "100", {"unit_of_measurement": "MWh"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
    base = {"brand": "Acme", "model": "Stack", "regions": "AU", "chemistry": "LFP", "phases": ["1", "3"],
            "unit_type": "module", "usable_kwh": 5, "warranty_years": 10, "eol_capacity_pct": 60,
            "throughput_basis": "discharged", "throughput_scope": "table", "throughput_table": "oops"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], base)
    assert result["errors"] == {"throughput_table": "bad_table"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**base, "throughput_table": "2=20000\n3=30000"})
    assert result["step_id"] == "group"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"units": 4, "install_date": "2026-01-01"})
    assert result["errors"] == {"units": "bad_units"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"units": 3, "install_date": "2026-01-01"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "sensors"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"integration": "manual"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Acme", "currency": "AUD", "charged_energy_entity": CHARGED})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # 100 MWh converted to kWh; no discharged sensor so it falls back to charged
    assert float(hass.states.get("sensor.acme_throughput_used").state) == pytest.approx(100000)
    assert hass.states.get("sensor.acme_warranty_status").state == "expired"
    assert hass.states.get("sensor.acme_cost_consumed").state == "unavailable"
