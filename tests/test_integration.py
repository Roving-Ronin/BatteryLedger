"""End-to-end tests: config flow, sensors, Store revisions. Needs pytest-homeassistant-custom-component."""

import copy
from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.battery_ledger.const import DOMAIN
from custom_components.battery_ledger.store_client import async_get_store_index

CHARGED = "sensor.sigen_plant_total_charged_energy_of_the_ess"
RATED = "sensor.sigen_plant_rated_energy_capacity"




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
        result["flow_id"], {"search": "bat 8", "brand": "Sigenergy", "series": "Sigenergy|SigenStor", "region": "AU", "phase": "3"})
    assert result["step_id"] == "store_select"
    assert result["description_placeholders"]["matches"] == "1"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"spec_ids": ["sigenergy-sigenstor-bat-8-0-anz"]})
    assert result["step_id"] == "group"
    assert result["description_placeholders"]["tp_unit"] == "23.77 MWh"

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


async def test_mixed_models_in_one_pass(hass: HomeAssistant):
    """Tick BAT 8.0 and BAT 10.0 together; each gets its own count and warranty start date."""
    hass.config.country = "AU"
    hass.states.async_set(CHARGED, "1000", {"unit_of_measurement": "kWh"})
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    series_key = next(k for k in r["data_schema"].schema if str(k) == "series")
    names = [o["label"] for o in r["data_schema"].schema[series_key].config["options"]]
    assert "SigenStor (Sigenergy)" in names
    r = await flow.async_configure(r["flow_id"], {"brand": "Sigenergy", "series": "Sigenergy|SigenStor",
                                                  "region": "AU"})
    assert r["description_placeholders"]["matches"] == "4"
    r = await flow.async_configure(r["flow_id"], {"spec_ids": []})
    assert r["errors"] == {"base": "none_selected"}
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sigenergy-sigenstor-bat-8-0-anz",
                                                               "sigenergy-sigenstor-bat-10-0-anz"]})
    assert r["step_id"] == "group" and r["description_placeholders"]["remaining"] == "1"
    assert "BAT 10.0" in r["description_placeholders"]["name"]  # Store order: largest first
    r = await flow.async_configure(r["flow_id"], {"units": 2, "install_date": "2025-07-18"})
    assert r["step_id"] == "group" and r["description_placeholders"]["remaining"] == "0"
    assert "BAT 8.0" in r["description_placeholders"]["name"]
    r = await flow.async_configure(r["flow_id"], {"units": 4, "install_date": "2024-03-01"})
    assert r["step_id"] == "add_more"
    assert "· 2025-07-18" in r["description_placeholders"]["groups"]
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    r = await flow.async_configure(r["flow_id"], {"integration": "manual"})
    r = await flow.async_configure(r["flow_id"], {"name": "Mixed", "currency": "AUD", "charged_energy_entity": CHARGED})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    groups = r["result"].data["groups"]
    assert [(g["spec"]["model"], g["units"]) for g in groups] == [("SigenStor BAT 10.0", 2), ("SigenStor BAT 8.0", 4)]
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.mixed_warranted_throughput").state) == 4 * 23770 + 2 * 26680


async def test_store_refresh_result_steps(hass: HomeAssistant):
    """Refresh outcome is its own step (no English built into the code)."""
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_refresh"})
    assert r["step_id"] == "store_refresh_failed"  # offline_store fixture
    assert r["description_placeholders"]["error"] == "offline"
    r = await flow.async_configure(r["flow_id"], {})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "user"
