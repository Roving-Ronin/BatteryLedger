"""End-to-end tests: config flow, sensors, Store revisions. Needs pytest-homeassistant-custom-component."""

import copy
from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.battery_ledger.const import DOMAIN, STARTUP_WAIT
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
    assert result["description_placeholders"]["count"] == "34"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "store_search"})
    assert result["step_id"] == "store_search"

    # Three-phase + search text narrows to the BAT 8.0
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"search": "bat 8", "brand": "Sigenergy", "region": "AU", "phase": "3"})
    # "bat 8" matches the SigenStor BAT 8.0 and the SigenStor Neo BAT 8.0, so Model is asked first
    assert result["step_id"] == "store_model"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"series": "Sigenergy|SigenStor"})
    assert result["step_id"] == "store_select"
    assert result["description_placeholders"]["matches"] == "1"
    assert result["description_placeholders"]["example_a"] == "SigenStor BAT 8.0"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"spec_ids": ["sigenergy-sigenstor-bat-8-0-anz"]})
    assert result["step_id"] == "group"
    assert result["description_placeholders"]["tp_unit"] == "23.77 MWh"

    with pytest.raises(InvalidData):  # selector max comes from the spec: 6 modules
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {"units": 7, "install_date": install_date})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"units": 6, "install_date": install_date, "cost": 26062})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "add_more"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "sensors"})
    assert result["step_id"] == "sensors"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"integration": "manual"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Sigen battery"})
    assert result["errors"] == {"base": "no_energy_entity"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Sigen battery",
         "charged_energy_entity": CHARGED, "reported_capacity_entity": RATED})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return hass.config_entries.async_get_entry(result["result"].entry_id)


async def test_flow_and_sensors(hass: HomeAssistant):
    install = (dt_util.now().date() - timedelta(days=487)).isoformat()
    entry = await _setup_via_flow(hass, install)
    assert entry.title == "Sigen battery"

    def val(object_id):
        return hass.states.get(f"sensor.battery_ledger_{object_id}")

    assert float(val("total_rated_throughput").state) == 142620
    assert float(val("remaining_rated_throughput").state) == 127735
    for removed in ("rated_life_used", "estimated_remaining_value", "remaining_usable_capacity",
                    "degradation_driver", "warranty_status"):
        assert val(removed) is None  # duplicates of the YAML attributes, not created
    assert float(val("cost_per_kwh_rated").state) == pytest.approx(0.1827, abs=0.0001)
    # Default currency style is the symbol, as in the YAML package
    assert val("cost_per_kwh_rated").attributes["unit_of_measurement"] == "$/kWh"
    assert val("cost_consumed_to_date").attributes["unit_of_measurement"] == "$"
    assert "device_class" not in val("cost_consumed_to_date").attributes
    assert float(val("cost_consumed_to_date").state) == pytest.approx(3474.93, abs=1)  # follows the driver (age)
    assert val("hardware_capacity_validation").state == "Match Verified"
    assert val("hardware_capacity_validation").attributes["reported_hardware_kwh"] == 48.36
    assert val("total_rated_throughput").attributes["total_pack_count"] == 6
    cost = val("cost_consumed_to_date").attributes
    assert cost["percent_of_rated_life_used"] == pytest.approx(10.44, abs=0.01)
    usable = val("estimated_usable_capacity").attributes
    assert usable["degradation_driver"] == "Age (Time Elapsed)"
    assert usable["warranty_status"] == "On Track / Normal"
    # Same attributes as the YAML package, nothing extra
    assert set(usable) == {"remaining_usable_kwh", "degradation_driver", "warranty_status",
                           "unit_of_measurement", "icon", "friendly_name"}
    assert usable["friendly_name"] == "Battery Estimated Usable Capacity"
    assert set(val("projected_warranted_throughput").attributes) == {"unit_of_measurement", "icon", "friendly_name"}
    assert val("total_rated_throughput").attributes["friendly_name"] == "Battery Total Rated Throughput"
    cycles = val("cycles_per_day")
    assert cycles.attributes["unit_of_measurement"] == "C/day" and cycles.attributes["state_class"] == "measurement"
    assert float(cycles.state) == pytest.approx(14885 / 487 / 48.36, abs=0.0001)
    assert float(val("initial_usable_capacity").state) == pytest.approx(46.8)

    # Energy counter moves -> recalculated after the debounce
    hass.states.async_set(CHARGED, "20000", {"unit_of_measurement": "kWh"})
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()
    assert float(val("rated_throughput_used").state) == pytest.approx(20000)

    # Source drops out mid-run -> its last valid reading is kept, values don't jump
    hass.states.async_set(CHARGED, "unavailable")
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()
    assert float(val("rated_throughput_used").state) == pytest.approx(20000)


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
        result["flow_id"], {"name": "Acme", "charged_energy_entity": CHARGED})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # 100 MWh converted to kWh; no discharged sensor so it falls back to charged
    assert float(hass.states.get("sensor.battery_ledger_rated_throughput_used").state) == pytest.approx(100000)
    assert hass.states.get("sensor.battery_ledger_estimated_usable_capacity").attributes["warranty_status"] == "Warranty Ended"
    assert hass.states.get("sensor.battery_ledger_cost_consumed_to_date").state == "unavailable"


async def test_mixed_models_in_one_pass(hass: HomeAssistant):
    """Tick BAT 8.0 and BAT 10.0 together; each gets its own count and warranty start date."""
    hass.config.country = "AU"
    hass.states.async_set(CHARGED, "1000", {"unit_of_measurement": "kWh"})
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "Sigenergy", "region": "AU"})
    r = await flow.async_configure(r["flow_id"], {"series": "Sigenergy|SigenStor"})
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
    r = await flow.async_configure(r["flow_id"], {"name": "Mixed", "charged_energy_entity": CHARGED})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    groups = r["result"].data["groups"]
    assert [(g["spec"]["model"], g["units"]) for g in groups] == [("SigenStor BAT 10.0", 2), ("SigenStor BAT 8.0", 4)]
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.battery_ledger_total_rated_throughput").state) == 4 * 23770 + 2 * 26680


async def test_store_refresh_result_steps(hass: HomeAssistant):
    """Refresh outcome is its own step (no English built into the code)."""
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_refresh"})
    assert r["step_id"] == "store_refresh_failed"  # offline_store fixture
    assert r["description_placeholders"]["error"] == "offline"
    r = await flow.async_configure(r["flow_id"], {})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "user"


async def test_currency_symbol_and_default_name(hass: HomeAssistant):
    """Currency comes from HA; symbol style changes cost per kWh only; name defaults to '<Brand> Battery'."""
    hass.config.currency = "EUR"
    hass.states.async_set(CHARGED, "100", {"unit_of_measurement": "kWh"})
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"search": "bat 5", "brand": "Sigenergy"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sigenergy-sigenstor-bat-5-0-anz"]})
    r = await flow.async_configure(r["flow_id"], {"units": 1, "install_date": "2025-01-01", "cost": 5000})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    r = await flow.async_configure(r["flow_id"], {"integration": "manual"})
    assert r["step_id"] == "system"
    assert r["description_placeholders"]["currency"] == "EUR" and r["description_placeholders"]["symbol"] == "€"
    name_key = next(k for k in r["data_schema"].schema if str(k) == "name")
    assert name_key.default() == "Sigenergy Battery"
    r = await flow.async_configure(r["flow_id"], {"name": "Sigenergy Battery",
                                                  "currency_style": "code", "charged_energy_entity": CHARGED})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["title"] == "Sigenergy Battery"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.battery_ledger_cost_per_kwh_rated").attributes["unit_of_measurement"] == "EUR/kWh"
    consumed = hass.states.get("sensor.battery_ledger_cost_consumed_to_date").attributes
    # Code style: monetary device class, so HA formats it as currency in the user's locale
    assert consumed["unit_of_measurement"] == "EUR" and consumed["device_class"] == "monetary"
    # Friendly names never include the brand
    assert consumed["friendly_name"] == "Battery Cost Consumed To Date"


async def test_model_step_follows_brand(hass: HomeAssistant):
    """The Model list only offers models among the batteries matching the other filters."""
    flow = hass.config_entries.flow

    async def models_for(filters):
        r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
        r = await flow.async_configure(r["flow_id"], filters)
        if r["step_id"] != "store_model":
            return r["step_id"], None, r
        key = next(k for k in r["data_schema"].schema if str(k) == "series")
        return r["step_id"], [o["label"] for o in r["data_schema"].schema[key].config["options"]], r

    # Sungrow: only its own models, labelled without the brand
    step, labels, r = await models_for({"brand": "Sungrow"})
    assert step == "store_model" and labels == ["SBH", "SBR"]
    r = await flow.async_configure(r["flow_id"], {"series": "Sungrow|SBR"})
    assert r["step_id"] == "store_select" and r["description_placeholders"]["matches"] == "1"
    # Sigenergy: SigenStor and SigenStor Neo
    step, labels, _ = await models_for({"brand": "Sigenergy"})
    assert step == "store_model" and labels == ["SigenStor", "SigenStor Neo"]
    # Huawei has one model, so the step is skipped
    step, labels, _ = await models_for({"brand": "Huawei"})
    assert step == "store_select"
    # No brand: every model, with its brand
    step, labels, r = await models_for({})
    assert labels == ["SMILE-G3 (AlphaESS)", "SMILE-M5 (AlphaESS)", "SMILE-T10-HV (AlphaESS)", "SMILE5 (AlphaESS)", "Battery-Box Premium HVM (BYD)", "Battery-Box Premium HVS (BYD)", "BOS-G (Deye)", "BOS-G Pro (Deye)", "RW (Deye)", "Spring AI (Deye)", "Spring SE (Deye)", "Reserva (Fronius)", "Reserva Pro (Fronius)", "Lynx Home F (GoodWe)", "Lynx Home F G2 (GoodWe)", "Lynx Home U (GoodWe)", "Lynx U G3 (GoodWe)", "LUNA2000 (Huawei)", "iStore Battery (iStore)", "SigenStor (Sigenergy)", "SigenStor Neo (Sigenergy)", "SBH (Sungrow)", "SBR (Sungrow)"]
    r = await flow.async_configure(r["flow_id"], {})  # left empty = all models
    assert r["description_placeholders"]["matches"] == "34"
    # Three-phase only excludes nothing for SBH, but a search narrows models too
    step, labels, _ = await models_for({"search": "sbh"})
    assert step == "store_select"


DISCHARGED = "sensor.sigen_plant_total_discharged_energy_of_the_ess"


async def _startup_entry(hass: HomeAssistant):
    """A BAT 8.0 x 6 entry (discharged-energy warranty) with charged, discharged and rated sensors."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.battery_ledger.const import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION
    index = await async_get_store_index(hass)
    spec = index.get("sigenergy-sigenstor-bat-8-0-anz")
    install = (dt_util.now().date() - timedelta(days=365)).isoformat()
    entry = MockConfigEntry(domain=DOMAIN, title="Sigen", version=CONFIG_ENTRY_VERSION,
                            minor_version=CONFIG_ENTRY_MINOR_VERSION, data={
        "name": "Sigen", "groups": [{"spec": spec, "units": 6, "install_date": install}],
        "charged_energy_entity": CHARGED, "discharged_energy_entity": DISCHARGED,
        "reported_capacity_entity": RATED})
    entry.add_to_hass(hass)
    return entry


async def test_waits_for_every_source_at_startup(hass: HomeAssistant):
    """A source still connecting isn't treated as not configured: no charged-energy fallback blip."""
    hass.states.async_set(CHARGED, "12000", {"unit_of_measurement": "kWh"})
    hass.states.async_set(DISCHARGED, "unavailable")
    hass.states.async_set(RATED, "48.36", {"unit_of_measurement": "kWh"})
    entry = await _startup_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    used = "sensor.battery_ledger_rated_throughput_used"
    assert not entry.runtime_data.ready
    assert hass.states.get(used).state == "unavailable"

    hass.states.async_set(DISCHARGED, "11000", {"unit_of_measurement": "kWh"})
    await hass.async_block_till_done()
    assert entry.runtime_data.ready
    assert float(hass.states.get(used).state) == pytest.approx(11000)  # discharged, as the warranty states
    assert "notes" not in hass.states.get(used).attributes or not hass.states.get(used).attributes["notes"]


async def test_startup_wait_times_out(hass: HomeAssistant):
    """A source that never reports doesn't hold the ledger back for good: fallback after the wait."""
    hass.states.async_set(CHARGED, "12000", {"unit_of_measurement": "kWh"})
    hass.states.async_set(RATED, "48.36", {"unit_of_measurement": "kWh"})
    entry = await _startup_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    used = "sensor.battery_ledger_rated_throughput_used"
    assert hass.states.get(used).state == "unavailable"

    async_fire_time_changed(hass, dt_util.utcnow() + STARTUP_WAIT + timedelta(seconds=1))
    await hass.async_block_till_done()
    state = hass.states.get(used)
    assert float(state.state) == pytest.approx(12000)  # charged fallback, with its note
    assert "discharged_sensor_missing_using_charged" in state.attributes["notes"]


async def test_source_dropout_keeps_basis(hass: HomeAssistant):
    """Discharged counter drops out mid-run: keep its last reading, don't switch to charged."""
    hass.states.async_set(CHARGED, "12000", {"unit_of_measurement": "kWh"})
    hass.states.async_set(DISCHARGED, "11", {"unit_of_measurement": "MWh"})
    hass.states.async_set(RATED, "48.36", {"unit_of_measurement": "kWh"})
    entry = await _startup_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    used = "sensor.battery_ledger_rated_throughput_used"
    assert float(hass.states.get(used).state) == pytest.approx(11000)

    hass.states.async_set(DISCHARGED, "unavailable")  # unit attribute gone too
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()
    assert float(hass.states.get(used).state) == pytest.approx(11000)
    assert "discharged_sensor_missing_using_charged" not in (hass.states.get(used).attributes.get("notes") or [])


async def test_options_cost_per_group(hass: HomeAssistant):
    """Options: each battery group's cost is set on its own form; a cleared cost is removed."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.battery_ledger.const import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION
    index = await async_get_store_index(hass)
    spec = index.get("sigenergy-sigenstor-bat-8-0-anz")
    groups = [{"spec": spec, "units": 4, "install_date": "2024-01-01", "cost": 20000},
              {"spec": spec, "units": 2, "install_date": "2025-06-01"}]
    entry = MockConfigEntry(domain=DOMAIN, title="Sigen", version=CONFIG_ENTRY_VERSION,
                            minor_version=CONFIG_ENTRY_MINOR_VERSION,
                            data={"name": "Sigen", "groups": groups, "charged_energy_entity": CHARGED})
    entry.add_to_hass(hass)
    hass.states.async_set(CHARGED, "1000", {"unit_of_measurement": "kWh"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "costs"})
    assert r["description_placeholders"]["number"] == "1" and r["description_placeholders"]["total"] == "2"
    cost_key = next(k for k in r["data_schema"].schema if str(k) == "cost")
    assert cost_key.description["suggested_value"] == 20000
    r = await hass.config_entries.options.async_configure(r["flow_id"], {})  # cleared
    assert r["description_placeholders"]["install_date"] == "2025-06-01"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"cost": 8000})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "cost" not in entry.data["groups"][0] and entry.data["groups"][1]["cost"] == 8000
    attrs = hass.states.get("sensor.battery_ledger_cost_consumed_to_date")
    assert attrs is not None and float(attrs.state) > 0


async def test_soh_of_zero_is_not_reported(hass: HomeAssistant):
    """An SoH source publishing 0% (e.g. Energy Manager on an inverter without SoH) counts as no reading:
    SoH Above Warranty Floor is unavailable rather than about -97%, and the projected SoH is unaffected."""
    soh = "sensor.inverter_battery_soh"
    hass.states.async_set(CHARGED, "12000", {"unit_of_measurement": "kWh"})
    hass.states.async_set(DISCHARGED, "11000", {"unit_of_measurement": "kWh"})
    hass.states.async_set(RATED, "48.36", {"unit_of_measurement": "kWh"})
    hass.states.async_set(soh, "0", {"unit_of_measurement": "%"})
    entry = await _startup_entry(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "soh_entity": soh})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    margin = hass.states.get("sensor.battery_ledger_soh_above_warranty_floor")
    assert margin.state == "unavailable" or margin.attributes.get("reported_soh_pct") is None
    assert float(hass.states.get("sensor.battery_ledger_estimated_usable_capacity").state) > 90

    hass.states.async_set(soh, "98.5", {"unit_of_measurement": "%"})
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()
    margin = hass.states.get("sensor.battery_ledger_soh_above_warranty_floor")
    assert margin.attributes["reported_soh_pct"] == 98.5 and float(margin.state) > 0


async def _two_group_entry(hass: HomeAssistant):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.battery_ledger.const import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION
    index = await async_get_store_index(hass)
    spec = index.get("sigenergy-sigenstor-bat-8-0-anz")
    groups = [{"spec": spec, "units": 4, "install_date": "2024-01-01", "cost": 20000},
              {"spec": spec, "units": 2, "install_date": "2025-06-01", "cost": 8000}]
    modules = [{"id": m, "group": g, "discharged_entity": f"sensor.{m.lower()}_discharged", "soc_entity": None}
               for m, g in (("A1", 0), ("B1", 1), ("B2", 1))]
    entry = MockConfigEntry(domain=DOMAIN, title="Sigen", version=CONFIG_ENTRY_VERSION,
                            minor_version=CONFIG_ENTRY_MINOR_VERSION,
                            data={"name": "Sigen", "groups": groups, "modules": modules,
                                  "charged_energy_entity": CHARGED})
    entry.add_to_hass(hass)
    hass.states.async_set(CHARGED, "1000", {"unit_of_measurement": "kWh"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _open_group(hass: HomeAssistant, entry, index: str):
    opts = hass.config_entries.options
    r = await opts.async_init(entry.entry_id)
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "groups"})
    assert r["type"] is FlowResultType.MENU and "4 × Sigenergy" in r["description_placeholders"]["groups"]
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "group_pick"})
    assert r["step_id"] == "group_pick"
    return await opts.async_configure(r["flow_id"], {"group": index})


async def test_options_group_edit_units_and_date(hass: HomeAssistant):
    """Options → Battery groups: a wrong unit count or warranty start can be corrected."""
    entry = await _two_group_entry(hass)
    r = await _open_group(hass, entry, "1")
    assert r["step_id"] == "group_edit" and r["description_placeholders"]["number"] == "2"
    suggested = {str(k): k.description["suggested_value"] for k in r["data_schema"].schema
                 if k.description and "suggested_value" in k.description}
    assert suggested == {"units": 2, "install_date": "2025-06-01"}

    opts = hass.config_entries.options
    future = (dt_util.now().date() + timedelta(days=3)).isoformat()
    r = await opts.async_configure(r["flow_id"], {"units": 3, "install_date": future})
    assert r["errors"] == {"install_date": "future_date"}
    r = await opts.async_configure(r["flow_id"], {"units": 3, "install_date": "2025-05-20"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    g = entry.data["groups"][1]
    assert (g["units"], g["install_date"], g["cost"]) == (3, "2025-05-20", 8000)
    assert entry.data["groups"][0]["units"] == 4


async def test_options_group_bad_units(hass: HomeAssistant):
    """A unit count the warranty table doesn't cover is refused, listing the allowed counts."""
    entry = await _two_group_entry(hass)
    spec = copy.deepcopy(entry.data["groups"][0]["spec"])
    spec["warranty"]["throughput"] = {**spec["warranty"]["throughput"], "scope": "table",
                                        "table": [{"units": 2, "kwh": 1}, {"units": 4, "kwh": 2}]}
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "groups": [{**entry.data["groups"][0], "spec": spec}, entry.data["groups"][1]]})
    await hass.async_block_till_done()
    r = await _open_group(hass, entry, "0")
    assert r["description_placeholders"]["allowed"] == "2, 4"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"units": 3, "install_date": "2024-01-01"})
    assert r["errors"] == {"units": "bad_units"}


async def test_options_group_remove_reindexes_modules(hass: HomeAssistant):
    """Removing a group drops its cost and modules; modules of later groups move down."""
    entry = await _two_group_entry(hass)
    r = await _open_group(hass, entry, "0")
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"units": 4, "install_date": "2024-01-01", "remove": True})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert [(g["units"], g["cost"]) for g in entry.data["groups"]] == [(2, 8000)]
    assert [(m["id"], m["group"]) for m in entry.data["modules"]] == [("B1", 0), ("B2", 0)]


async def test_options_group_remove_last_refused(hass: HomeAssistant):
    """The only group can't be removed; with one group the pick step is skipped."""
    entry = await _two_group_entry(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "groups": entry.data["groups"][:1],
                                                        "modules": entry.data["modules"][:1]})
    await hass.async_block_till_done()
    opts = hass.config_entries.options
    r = await opts.async_init(entry.entry_id)
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "groups"})
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "group_pick"})
    assert r["step_id"] == "group_edit"
    r = await opts.async_configure(r["flow_id"], {"units": 4, "install_date": "2024-01-01", "remove": True})
    assert r["errors"] == {"base": "last_group"}
    assert len(entry.data["groups"]) == 1


def test_mix_example_uses_the_batteries_shown():
    """'Tick every model … e.g. both X and Y': X and Y come from the batteries on the form, then the same brand."""
    from custom_components.battery_ledger.config_flow import _mix_example
    luna7 = {"brand": "Huawei", "model": "LUNA2000-7-S1"}
    luna5 = {"brand": "Huawei", "model": "LUNA2000-5-S0"}
    bat8 = {"brand": "Sigenergy", "model": "SigenStor BAT 8.0"}
    bat10 = {"brand": "Sigenergy", "model": "SigenStor BAT 10.0"}
    store = [bat10, bat8, luna7, luna5]
    assert _mix_example([luna7, luna5], store) == ("LUNA2000-7-S1", "LUNA2000-5-S0")
    assert _mix_example([luna5], store) == ("LUNA2000-5-S0", "LUNA2000-7-S1")  # one shown: same brand next
    assert _mix_example([bat8, bat8], store) == ("SigenStor BAT 8.0", "SigenStor BAT 10.0")
