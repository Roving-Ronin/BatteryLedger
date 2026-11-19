"""Sensor-profile detection and the module setup path."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.battery_ledger.const import DOMAIN, STARTUP_WAIT
from custom_components.battery_ledger.detect import RegistryEntity, assign_modules, detect

SNAPSHOT = Path(__file__).resolve().parent.parent / "custom_components" / "battery_ledger" / "data" / "index_snapshot.json"
PROFILES = {p["id"]: p for p in json.loads(SNAPSHOT.read_text())["profiles"]}
TYP_ENTRY = "01JCX4ZQ8T5V2M3N4P5Q6R7S8T"
STATION = "203840556"
SERIALS = ["110b13641026", "110b13641048"]


async def _past_startup_wait(hass):
    """Move past BatteryLedger's startup wait for source sensors."""
    async_fire_time_changed(hass, dt_util.utcnow() + STARTUP_WAIT + timedelta(seconds=1))
    await hass.async_block_till_done()




def typqxq_entities():
    return [
        RegistryEntity("sensor.sigen_plant_total_discharged_energy_of_the_ess", "sigen",
                       f"{TYP_ENTRY}_sigen_plant_plant_accumulated_battery_discharge_energy"),
        RegistryEntity("sensor.sigen_plant_total_charged_energy_of_the_ess", "sigen",
                       f"{TYP_ENTRY}_sigen_plant_plant_accumulated_battery_charge_energy"),
        RegistryEntity("sensor.sigen_plant_rated_energy_capacity", "sigen",
                       f"{TYP_ENTRY}_sigen_plant_plant_ess_rated_energy_capacity"),
        RegistryEntity("sensor.sigen_plant_battery_state_of_health", "sigen",
                       f"{TYP_ENTRY}_sigen_plant_plant_ess_soh"),
        RegistryEntity("sensor.sigen_inverter_ess_total_discharged", "sigen",
                       f"{TYP_ENTRY}_sigen_inverter_inverter_ess_accumulated_discharge_energy"),
    ]


def mqtt_entities():
    ents = [
        RegistryEntity("sensor.sigen_0_accumulated_discharge_energy", "mqtt", "sigen_0_accumulated_discharge_energy"),
        RegistryEntity("sensor.sigen_0_inverter_2_accumulated_discharge_energy", "mqtt", "sigen_0_002_30574"),
        RegistryEntity("sensor.sigen_0_accumulated_charge_energy", "mqtt", "sigen_0_accumulated_charge_energy"),
        RegistryEntity("sensor.sigen_0_plant_rated_energy_capacity", "mqtt", "sigen_0_247_30083"),
        RegistryEntity("sensor.sigen_0_plant_battery_soh", "mqtt", "sigen_0_247_30087"),
        RegistryEntity("sensor.sigen_0_cloud_gateway_communication_status", "mqtt",
                       f"sigen_0_{STATION}_gateway_communication_status"),
        RegistryEntity("sensor.other_device_energy", "mqtt", "zigbee_0x1234_energy"),
    ]
    for sn in SERIALS:
        for suffix in ("total_discharge_amount", "battery_soc", "rated_battery_capacity"):
            ents.append(RegistryEntity(f"sensor.sigen_0_cloud_4_{sn}_{suffix}", "mqtt", f"sigen_0_{STATION}_4_{sn}_{suffix}"))
    return ents


def test_detect_typqxq_prefers_plant_level():
    [system] = detect(PROFILES["sigen-local-modbus"], typqxq_entities() + mqtt_entities())
    assert system.roles["discharged_energy"] == ("plant", "sensor.sigen_plant_total_discharged_energy_of_the_ess")
    assert system.roles["soh"][1] == "sensor.sigen_plant_battery_state_of_health"
    assert not system.modules


def test_detect_sigenergy2mqtt_with_modules():
    [system] = detect(PROFILES["sigenergy2mqtt"], mqtt_entities() + typqxq_entities())
    assert system.roles["discharged_energy"] == ("plant", "sensor.sigen_0_accumulated_discharge_energy")
    assert system.roles["rated_capacity"][1] == "sensor.sigen_0_plant_rated_energy_capacity"
    assert set(system.modules) == set(SERIALS)
    assert system.modules[SERIALS[0]]["module_soc"] == f"sensor.sigen_0_cloud_4_{SERIALS[0]}_battery_soc"
    assert system.key == "prefix=sigen|plant=0"


def test_inverter_level_used_when_no_plant_sensor():
    ents = [e for e in mqtt_entities() if e.unique_id != "sigen_0_accumulated_discharge_energy"]
    [system] = detect(PROFILES["sigenergy2mqtt"], ents)
    assert system.roles["discharged_energy"] == ("inverter", "sensor.sigen_0_inverter_2_accumulated_discharge_energy")
    ents.append(RegistryEntity("sensor.sigen_0_inverter_3_accumulated_discharge_energy", "mqtt", "sigen_0_003_30574"))
    [system] = detect(PROFILES["sigenergy2mqtt"], ents)
    assert "discharged_energy" in system.ambiguous


def test_assign_modules_by_capacity():
    out, unassigned, counts = assign_modules({"a": 8.06, "b": 9.04, "c": 8.06}, [(8.06, 2), (9.04, 1)])
    assert out == {"a": 0, "b": 1, "c": 0} and unassigned == [] and counts == [(2, 2), (1, 1)]
    out, unassigned, counts = assign_modules({"a": 8.06, "b": None}, [(8.06, 1), (9.04, 1)])
    assert unassigned == ["b"] and counts == [(1, 1), (0, 1)]


async def test_flow_with_sigenergy2mqtt_modules(hass: HomeAssistant):
    hass.config.country, hass.config.currency = "AU", "AUD"
    registry = er.async_get(hass)
    owner = MockConfigEntry(domain="mqtt")
    owner.add_to_hass(hass)
    states = {
        "sigen_0_accumulated_discharge_energy": "1500",
        "sigen_0_247_30083": "16.12",
        "sigen_0_247_30087": "99",
        f"sigen_0_{STATION}_4_{SERIALS[0]}_total_discharge_amount": "700",
        f"sigen_0_{STATION}_4_{SERIALS[1]}_total_discharge_amount": "780",
        f"sigen_0_{STATION}_4_{SERIALS[0]}_battery_soc": "54",
        f"sigen_0_{STATION}_4_{SERIALS[1]}_battery_soc": "57",
        f"sigen_0_{STATION}_4_{SERIALS[0]}_rated_battery_capacity": "8.06",
        f"sigen_0_{STATION}_4_{SERIALS[1]}_rated_battery_capacity": "8.06",
    }
    for ent in mqtt_entities():
        object_id = ent.entity_id.split(".", 1)[1]
        registry.async_get_or_create("sensor", "mqtt", ent.unique_id, suggested_object_id=object_id,
                                     config_entry=owner)
        if ent.unique_id in states:
            hass.states.async_set(ent.entity_id, states[ent.unique_id], {"unit_of_measurement": "kWh"})

    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"search": "bat 8", "brand": "Sigenergy", "region": "AU"})
    r = await flow.async_configure(r["flow_id"], {"series": "Sigenergy|SigenStor"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sigenergy-sigenstor-bat-8-0-anz"]})
    install = (dt_util.now().date() - timedelta(days=365)).isoformat()
    r = await flow.async_configure(r["flow_id"], {"units": 2, "install_date": install})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    assert r["step_id"] == "sensors"
    options = r["data_schema"].schema["integration"].config["options"]
    values = [o["value"] for o in options]
    assert "sigenergy2mqtt|prefix=sigen|plant=0" in values
    assert "sigen-local-modbus|none" in values  # listed, but not installed
    # Sigenergy: its own integrations, then Energy Manager
    profile_ids = [v.split("|")[0] for v in values if v != "manual"]
    assert profile_ids == ["sigen-local-modbus", "sigenergy2mqtt", "energy-manager"]

    r = await flow.async_configure(r["flow_id"], {"integration": "sigen-local-modbus|none"})
    assert r["errors"] == {"integration": "not_detected"}
    r = await flow.async_configure(r["flow_id"], {"integration": "sigenergy2mqtt|prefix=sigen|plant=0"})
    assert r["step_id"] == "modules"
    assert "2 / 2 ✓" in r["description_placeholders"]["per_group"]
    r = await flow.async_configure(r["flow_id"], {"use_modules": True})
    assert r["step_id"] == "system"
    assert r["description_placeholders"]["modules"] == "2"
    assert r["description_placeholders"]["profile"] == "sigenergy2mqtt (MQTT)"
    suggested = {str(k): k.description["suggested_value"] for k in r["data_schema"].schema
                 if k.description and "suggested_value" in k.description}
    assert suggested["discharged_energy_entity"] == "sensor.sigen_0_accumulated_discharge_energy"
    assert suggested["soh_entity"] == "sensor.sigen_0_plant_battery_soh"

    r = await flow.async_configure(r["flow_id"], {"name": "Sigen", **suggested})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await _past_startup_wait(hass)  # some configured sensors never report here

    def st(obj):
        return hass.states.get(f"sensor.battery_ledger_{obj}")

    assert float(st("rated_throughput_used").state) == pytest.approx(1480)
    assert float(st("most_used_module_throughput").state) == pytest.approx(780 / 23770 * 100, abs=0.01)
    assert st("most_used_module_throughput").attributes["worst_module"] == SERIALS[1]
    assert float(st("module_soc_spread").state) == pytest.approx(3)
    margin = float(st("soh_above_warranty_floor").state)
    assert margin == pytest.approx(99 - float(st("estimated_usable_capacity").state), abs=0.1)
    assert st("hardware_capacity_validation").state == "Match Verified"


def em_entities():
    return [
        RegistryEntity("sensor.inverter_total_battery_discharge", "mqtt", "inverter_total_battery_discharge_mqtt"),
        RegistryEntity("sensor.inverter_total_battery_charge", "mqtt", "inverter_total_battery_charge_mqtt"),
        RegistryEntity("sensor.inverter_battery_capacity", "mqtt", "inverter_battery_capacity_mqtt"),
        RegistryEntity("sensor.inverter_battery_soh", "mqtt", "inverter_battery_soh_mqtt"),
        RegistryEntity("input_datetime.battery_install_date", "input_datetime", "battery_install_date"),
    ]


def test_detect_energy_manager_fixed_ids_and_helper_platform():
    [system] = detect(PROFILES["energy-manager"], em_entities() + mqtt_entities())
    assert system.roles["discharged_energy"] == ("plant", "sensor.inverter_total_battery_discharge")
    assert system.roles["soh"][1] == "sensor.inverter_battery_soh"
    assert system.roles["install_date"][1] == "input_datetime.battery_install_date"
    assert system.key == "default" and not system.modules


async def test_energy_manager_offered_for_any_brand_and_prefills_date(hass: HomeAssistant):
    registry = er.async_get(hass)
    mqtt_owner = MockConfigEntry(domain="mqtt")
    mqtt_owner.add_to_hass(hass)
    for ent in em_entities():
        domain, object_id = ent.entity_id.split(".", 1)
        registry.async_get_or_create(domain, ent.platform, ent.unique_id, suggested_object_id=object_id,
                                     config_entry=mqtt_owner if ent.platform == "mqtt" else None)
    hass.states.async_set("input_datetime.battery_install_date", "2024-11-02")
    hass.states.async_set("sensor.inverter_total_battery_discharge", "500", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.inverter_battery_capacity", "12.8", {"unit_of_measurement": "kWh"})

    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "Sungrow"})
    r = await flow.async_configure(r["flow_id"], {"series": "Sungrow|SBR"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sungrow-sbr-battery-module-3-2-kwh-au"]})
    assert r["step_id"] == "group"
    date_key = next(k for k in r["data_schema"].schema if str(k) == "install_date")
    assert date_key.description["suggested_value"] == "2024-11-02"  # from Energy Manager's helper
    r = await flow.async_configure(r["flow_id"], {"units": 4, "install_date": "2024-11-02"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    values = [o["value"] for o in r["data_schema"].schema["integration"].config["options"]]
    assert "energy-manager|default" in values  # offered for Sungrow, a brand with no own profile
    r = await flow.async_configure(r["flow_id"], {"integration": "energy-manager|default"})
    assert r["step_id"] == "system"
    suggested = {str(k): k.description["suggested_value"] for k in r["data_schema"].schema
                 if k.description and "suggested_value" in k.description}
    assert suggested == {"charged_energy_entity": "sensor.inverter_total_battery_charge",
                         "discharged_energy_entity": "sensor.inverter_total_battery_discharge",
                         "reported_capacity_entity": "sensor.inverter_battery_capacity",
                         "soh_entity": "sensor.inverter_battery_soh"}
    r = await flow.async_configure(r["flow_id"], {"name": "Sungrow Battery", **suggested})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await _past_startup_wait(hass)  # some configured sensors never report here
    # 4 x 8,960 kWh (V8.0), discharged basis from Energy Manager's discharge sensor
    assert float(hass.states.get("sensor.battery_ledger_total_rated_throughput").state) == 4 * 8960
    assert float(hass.states.get("sensor.battery_ledger_rated_throughput_used").state) == pytest.approx(500)


def test_detect_sungrow_integrations():
    mk = [RegistryEntity("sensor.total_battery_discharge", "modbus", "sg_total_battery_discharge"),
          RegistryEntity("sensor.total_battery_charge", "modbus", "sg_total_battery_charge"),
          RegistryEntity("sensor.battery_capacity_high_precision", "modbus", "uid_battery_capacity_high_precision"),
          RegistryEntity("sensor.battery_state_of_health", "modbus", "sg_battery_state_of_health"),
          RegistryEntity("sensor.total_battery_charge_from_pv", "modbus", "sg_total_battery_charge_from_pv")]
    [system] = detect(PROFILES["sungrow-shx-modbus-mkaiser"], mk)
    assert system.roles["discharged_energy"][1] == "sensor.total_battery_discharge"
    assert system.roles["charged_energy"][1] == "sensor.total_battery_charge"  # not "...from_pv"

    sn = "A2331234567"
    wm = [RegistryEntity(f"sensor.sungrow_shx_inverter_sh10rt_{k}", "sungrow_shx_inverter", f"{sn}_{k}")
          for k in ("total_battery_discharge", "total_battery_charge", "battery_capacity_high_precision",
                    "battery_state_of_health", "total_battery_charge_from_pv")]
    [system] = detect(PROFILES["sungrow-shx-inverter-wingman3434"], wm)
    assert system.roles["soh"][1] == "sensor.sungrow_shx_inverter_sh10rt_battery_state_of_health"
    assert system.roles["charged_energy"][1] == "sensor.sungrow_shx_inverter_sh10rt_total_battery_charge"


async def test_sungrow_integration_choices(hass: HomeAssistant):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "Sungrow"})
    r = await flow.async_configure(r["flow_id"], {"series": "Sungrow|SBH"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sungrow-sbh-battery-module-5-0-kwh-au"]})
    r = await flow.async_configure(r["flow_id"], {"units": 4, "install_date": "2025-01-01"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    ids = [o["value"].split("|")[0] for o in r["data_schema"].schema["integration"].config["options"]]
    assert ids == ["sungrow-shx-inverter-wingman3434", "sungrow-shx-modbus-mkaiser", "energy-manager", "manual"]


def test_detect_huawei_solar():
    sn = "HV2280123456"
    ents = [RegistryEntity(f"sensor.batteries_{k}", "huawei_solar", f"{sn}_storage_{k}")
            for k in ("total_discharge", "total_charge", "rated_capacity", "state_of_capacity")]
    ents.append(RegistryEntity("sensor.battery_1_total_discharge", "huawei_solar", f"{sn}_storage_unit_1_total_discharge"))
    [system] = detect(PROFILES["huawei-solar-wlcrs"], ents)
    assert system.roles["discharged_energy"][1] == "sensor.batteries_total_discharge"
    assert system.roles["charged_energy"][1] == "sensor.batteries_total_charge"
    assert system.roles["rated_capacity"][1] == "sensor.batteries_rated_capacity"


async def test_istore_offers_huawei_solar(hass: HomeAssistant):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "iStore"})
    assert r["step_id"] == "store_select"  # one model line, so the Model step is skipped
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["istore-is-batt-5000-es-au"]})
    r = await flow.async_configure(r["flow_id"], {"units": 3, "install_date": "2025-01-01"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    ids = [o["value"].split("|")[0] for o in r["data_schema"].schema["integration"].config["options"]]
    assert ids == ["huawei-solar-wlcrs", "energy-manager", "manual"]


def test_detect_alphaess_modbus():
    entry = "01JALPHAENTRY"
    ents = [RegistryEntity(f"sensor.alphaess_inverter_{name}", "alphaess_modbus", f"{entry}_{key}")
            for key, name in (("total_energy_discharge_battery", "total_energy_discharge_battery"),
                              ("total_energy_charge_battery", "total_energy_charge_battery"),
                              ("total_energy_charge_battery_from_grid", "total_energy_charge_battery_from_grid"),
                              ("battery_capacity_kwh", "battery_capacity"),
                              ("soh_battery", "battery_state_of_health"))]
    [system] = detect(PROFILES["alphaess-modbus-senalse"], ents)
    assert system.roles["discharged_energy"][1] == "sensor.alphaess_inverter_total_energy_discharge_battery"
    assert system.roles["charged_energy"][1] == "sensor.alphaess_inverter_total_energy_charge_battery"  # not "...from_grid"
    assert system.roles["rated_capacity"][1] == "sensor.alphaess_inverter_battery_capacity"
    assert system.roles["soh"][1] == "sensor.alphaess_inverter_battery_state_of_health"


async def test_alphaess_integration_choices(hass: HomeAssistant):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "AlphaESS"})
    r = await flow.async_configure(r["flow_id"], {"series": "AlphaESS|SMILE-M5"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["alphaess-smile-m-bat-13-9p-au"]})
    r = await flow.async_configure(r["flow_id"], {"units": 1, "install_date": "2025-09-01"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    ids = [o["value"].split("|")[0] for o in r["data_schema"].schema["integration"].config["options"]]
    assert ids == ["alphaess-modbus-senalse", "energy-manager", "manual"]


def test_detect_deye_solarman_and_esphome():
    entry = "01jdeyeentry0000000000000"  # solarman slugifies the config entry ID (lower case)
    ents = [RegistryEntity(f"sensor.inverter_{k}", "solarman", f"{entry}_{k}_sensor")
            for k in ("total_battery_discharge", "total_battery_charge", "daily_battery_charge", "battery_soh")]
    [system] = detect(PROFILES["deye-solarman-davidrapan"], ents)
    assert system.roles["discharged_energy"][1] == "sensor.inverter_total_battery_discharge"
    assert system.roles["charged_energy"][1] == "sensor.inverter_total_battery_charge"
    assert "soh" not in system.roles  # solarman's Battery SOH is its own estimate, not the BMS figure

    mac = "A4:CF:12:3B:9E:01"  # Home Assistant keeps the colons in ESPHome unique IDs
    ents = [RegistryEntity(f"sensor.deye_inverter_3b9e01_{k}", "esphome", f"{mac}-sensor-{k}")
            for k in ("total_battery_discharge", "total_battery_charge", "daily_battery_discharge")]
    [system] = detect(PROFILES["deye-esphome-lewa-reka"], ents)
    assert system.roles["discharged_energy"][1] == "sensor.deye_inverter_3b9e01_total_battery_discharge"
    assert system.roles["charged_energy"][1] == "sensor.deye_inverter_3b9e01_total_battery_charge"
    # Two ESPHome inverters are two systems
    other = [RegistryEntity(f"sensor.deye_inverter_77aa10_{k}", "esphome", f"a4cf1277aa10-sensor-{k}")
             for k in ("total_battery_discharge", "total_battery_charge")]
    assert len(detect(PROFILES["deye-esphome-lewa-reka"], ents + other)) == 2


async def test_deye_integration_choices(hass: HomeAssistant):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "Deye"})
    r = await flow.async_configure(r["flow_id"], {"series": "Deye|RW"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["deye-rw-m6-1-b-au"]})
    r = await flow.async_configure(r["flow_id"], {"units": 2, "install_date": "2025-09-01"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    ids = [o["value"].split("|")[0] for o in r["data_schema"].schema["integration"].config["options"]]
    assert ids == ["deye-esphome-lewa-reka", "deye-solarman-davidrapan", "energy-manager", "manual"]


def test_detect_goodwe():
    sn = "9010KETU000W1234"
    ents = [RegistryEntity(f"sensor.goodwe_{name}", "goodwe", f"goodwe-{key}-{sn}")
            for key, name in (("e_bat_discharge_total", "total_battery_discharge"),
                              ("e_bat_charge_total", "total_battery_charge"),
                              ("e_bat_charge_day", "today_battery_charge"),
                              ("battery_soh", "battery_state_of_health"))]
    [system] = detect(PROFILES["goodwe"], ents)
    assert system.roles["discharged_energy"][1] == "sensor.goodwe_total_battery_discharge"
    assert system.roles["charged_energy"][1] == "sensor.goodwe_total_battery_charge"  # not "today"
    assert system.roles["soh"][1] == "sensor.goodwe_battery_state_of_health"


async def test_goodwe_integration_choices(hass: HomeAssistant):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "GoodWe"})
    r = await flow.async_configure(r["flow_id"], {"series": "GoodWe|Lynx Home F"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["goodwe-lx-f3-3-h-anz"]})
    r = await flow.async_configure(r["flow_id"], {"units": 3, "install_date": "2024-03-01"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    ids = [o["value"].split("|")[0] for o in r["data_schema"].schema["integration"].config["options"]]
    assert ids == ["goodwe", "energy-manager", "manual"]


def test_detect_huawei_emma_stack():
    """A cascaded stack (up to 3 inverters) with an EMMA: the EMMA's site totals win over each inverter's."""
    ents = []
    for sn in ("HV1111111111", "HV2222222222", "HV3333333333"):
        ents += [RegistryEntity(f"sensor.batteries_{k}_{sn[-1]}", "huawei_solar", f"{sn}_storage_{k}")
                 for k in ("total_discharge", "total_charge", "rated_capacity")]
    # Without an EMMA, three inverters' totals are ambiguous: no sensors are filled in (chosen manually),
    # but each inverter's rated capacity is kept for suggesting the battery model
    [alone] = detect(PROFILES["huawei-solar-wlcrs"], ents)
    assert not alone.roles and sorted(alone.ambiguous) == ["charged_energy", "discharged_energy", "rated_capacity"]
    assert len(alone.inverters) == 3
    emma = "EMMA00000001"
    ents += [RegistryEntity(f"sensor.emma_{k}", "huawei_solar", f"{emma}_{k}")
             for k in ("total_discharged_energy", "total_charged_energy", "rated_ess_capacity", "charged_energy_today")]
    [system] = detect(PROFILES["huawei-solar-wlcrs"], ents)
    assert system.roles["discharged_energy"] == ("plant", "sensor.emma_total_discharged_energy")
    assert system.roles["charged_energy"] == ("plant", "sensor.emma_total_charged_energy")
    assert system.roles["rated_capacity"] == ("plant", "sensor.emma_rated_ess_capacity")
    assert not system.ambiguous


def test_detect_fronius_modbus_and_byd_battery_box():
    ents = [RegistryEntity("sensor.fronius_symo_gen24_10_0_plus_storage_charging_lifetime_energy", "fronius_modbus", "fm_mppt3_lfte"),
            RegistryEntity("sensor.fronius_symo_gen24_10_0_plus_storage_discharging_lifetime_energy", "fronius_modbus", "fm_mppt4_lfte"),
            RegistryEntity("sensor.fronius_symo_gen24_10_0_plus_mppt1_lifetime_energy", "fronius_modbus", "fm_mppt1_lfte"),
            RegistryEntity("sensor.byd_battery_box_premium_hv_capacity", "fronius_modbus", "fm_WHRtg")]
    [system] = detect(PROFILES["fronius-modbus-redpomodoro"], ents)
    assert system.roles["charged_energy"][1].endswith("_storage_charging_lifetime_energy")
    assert system.roles["discharged_energy"][1].endswith("_storage_discharging_lifetime_energy")
    assert system.roles["rated_capacity"][1] == "sensor.byd_battery_box_premium_hv_capacity"

    ents = [RegistryEntity(f"sensor.battery_management_unit_{n}", "byd_battery_box", f"bydb_{k}")
            for k, n in (("charge_lfte", "charge_total_energy"), ("discharge_lfte", "discharge_total_energy"),
                         ("soh", "state_of_health"), ("capacity", "total_capacity"))]
    ents.append(RegistryEntity("sensor.battery_management_system_1_discharge_total_energy", "byd_battery_box", "bydb_bms1_discharge_lfte"))
    [system] = detect(PROFILES["byd-battery-box-redpomodoro"], ents)
    assert system.roles["discharged_energy"][1] == "sensor.battery_management_unit_discharge_total_energy"  # the whole battery, not tower 1
    assert system.roles["soh"][1] == "sensor.battery_management_unit_state_of_health"


async def test_byd_integration_choices(hass: HomeAssistant):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "BYD"})
    r = await flow.async_configure(r["flow_id"], {"series": "BYD|Battery-Box Premium HVS"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["byd-hvs-module-2-56-kwh-au"]})
    r = await flow.async_configure(r["flow_id"], {"units": 4, "install_date": "2023-05-01"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    ids = [o["value"].split("|")[0] for o in r["data_schema"].schema["integration"].config["options"]]
    assert ids == ["byd-battery-box-redpomodoro", "fronius-modbus-redpomodoro", "energy-manager", "manual"]


def _register(hass, entities, *, disabled=(), owner_domain=None):
    """Registry entries for (entity_id, platform, unique_id); some disabled by their integration."""
    registry = er.async_get(hass)
    owner = None
    if owner_domain:
        owner = MockConfigEntry(domain=owner_domain)
        owner.add_to_hass(hass)
    for ent in entities:
        domain, object_id = ent.entity_id.split(".", 1)
        registry.async_get_or_create(
            domain, ent.platform, ent.unique_id, suggested_object_id=object_id, config_entry=owner,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION if ent.entity_id in disabled else None)


def typqxq_inverter_entities(inverter="sigen_inverter"):
    return [
        RegistryEntity(f"sensor.{inverter}_model_type", "sigen", f"{TYP_ENTRY}_{inverter}_inverter_model_type"),
        RegistryEntity(f"sensor.{inverter}_pack_count", "sigen", f"{TYP_ENTRY}_{inverter}_inverter_pack_count"),
        RegistryEntity(f"sensor.{inverter}_rated_battery_capacity", "sigen",
                       f"{TYP_ENTRY}_{inverter}_inverter_rated_battery_capacity"),
    ]


def test_detect_keeps_every_inverter():
    ents = typqxq_entities() + typqxq_inverter_entities() + typqxq_inverter_entities("sigen_inverter_2")
    [system] = detect(PROFILES["sigen-local-modbus"], ents)
    assert sorted(system.inverters) == ["device=sigen_inverter", "device=sigen_inverter_2"]
    assert system.inverters["device=sigen_inverter_2"]["inverter_pack_count"] == ["sensor.sigen_inverter_2_pack_count"]


async def test_detect_enables_sensors_and_suggests(hass: HomeAssistant, monkeypatch):
    """Sigen: the off-by-default pack count, model and capacity are turned on (with consent), then
    48.36 kWh over 6 packs on a SigenStor inverter pre-fills 6 x BAT 8.0 for the user to confirm."""
    from custom_components.battery_ledger import config_flow as cf

    monkeypatch.setattr(cf, "ENABLE_WAIT_ATTEMPTS", (0, 0))
    inv = typqxq_inverter_entities()
    _register(hass, typqxq_entities() + inv, disabled={e.entity_id for e in inv}, owner_domain="sigen")
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["menu_options"][0] == "detect"
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    assert r["step_id"] == "detect"
    r = await flow.async_configure(r["flow_id"], {"system": f"sigen-local-modbus|entry={TYP_ENTRY}"})
    assert r["step_id"] == "detect_enable" and r["description_placeholders"]["count"] == "3"

    # The user agrees; the integration then reports (states set as it would after reloading)
    r = await flow.async_configure(r["flow_id"], {"enable": True})
    registry = er.async_get(hass)
    assert all(not registry.async_get(e.entity_id).disabled for e in inv)
    hass.states.async_set("sensor.sigen_inverter_model_type", "SigenStor EC 30.0 TP AU")
    hass.states.async_set("sensor.sigen_inverter_pack_count", "6")
    hass.states.async_set("sensor.sigen_inverter_rated_battery_capacity", "48.36", {"unit_of_measurement": "kWh"})
    await hass.async_block_till_done()
    r = await flow.async_configure(r["flow_id"])
    assert r["step_id"] == "group"
    assert r["description_placeholders"]["name"] == "Sigenergy SigenStor BAT 8.0"
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert units_key.description["suggested_value"] == 6

    r = await flow.async_configure(r["flow_id"], {"units": 6, "install_date": "2025-07-18"})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    key = next(k for k in r["data_schema"].schema if str(k) == "integration")
    assert key.default() == f"sigen-local-modbus|entry={TYP_ENTRY}"


async def test_detect_without_consent_leaves_sensors_off(hass: HomeAssistant):
    """Declining leaves the other integration's sensors alone; capacity alone can still suggest."""
    inv = typqxq_inverter_entities()
    _register(hass, typqxq_entities() + inv, disabled={inv[0].entity_id, inv[1].entity_id}, owner_domain="sigen")
    hass.states.async_set("sensor.sigen_inverter_rated_battery_capacity", "24.18", {"unit_of_measurement": "kWh"})
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    r = await flow.async_configure(r["flow_id"], {"system": f"sigen-local-modbus|entry={TYP_ENTRY}"})
    r = await flow.async_configure(r["flow_id"], {"enable": False})
    assert er.async_get(hass).async_get(inv[1].entity_id).disabled
    # 24.18 kWh: 3 x BAT 8.0 or 4 x BAT 6.0 (or Neo) — the user picks; units follow the pick
    assert r["step_id"] == "store_select"
    options = [o["value"] for o in r["data_schema"].schema["spec_ids"].config["options"]]
    assert "sigenergy-sigenstor-bat-8-0-anz" in options and "sigenergy-sigenstor-bat-6-0-anz" in options
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sigenergy-sigenstor-bat-6-0-anz"]})
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert units_key.description["suggested_value"] == 4


async def test_detect_energy_manager_brand_dates_and_costs(hass: HomeAssistant):
    """Energy Manager: brand from inverter_brand, model and units from capacity, and the install
    dates and costs of the first and later batteries pre-fill each battery group."""
    ents = em_entities() + [
        RegistryEntity("input_select.inverter_brand", "input_select", "inverter_brand"),
        RegistryEntity("input_number.battery_install_cost", "input_number", "battery_install_cost"),
        RegistryEntity("input_datetime.battery_install_date_2", "input_datetime", "battery_install_date_2"),
        RegistryEntity("input_number.battery_install_cost_2", "input_number", "battery_install_cost_2"),
    ]
    _register(hass, [e for e in ents if e.platform == "mqtt"], owner_domain="mqtt")
    _register(hass, [e for e in ents if e.platform != "mqtt"])
    hass.states.async_set("input_select.inverter_brand", "sungrow")
    hass.states.async_set("sensor.inverter_battery_capacity", "9.6", {"unit_of_measurement": "kWh"})
    hass.states.async_set("input_datetime.battery_install_date", "2024-11-02")
    hass.states.async_set("input_number.battery_install_cost", "7200.0")
    hass.states.async_set("input_datetime.battery_install_date_2", "2025-06-01")
    hass.states.async_set("input_number.battery_install_cost_2", "2400.0")

    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    r = await flow.async_configure(r["flow_id"], {"system": "energy-manager|default"})
    assert r["step_id"] == "group"
    assert r["description_placeholders"]["name"] == "Sungrow SBR Battery Module 3.2 kWh"
    suggested = {str(k): k.description["suggested_value"] for k in r["data_schema"].schema
                 if k.description and "suggested_value" in k.description}
    assert suggested == {"units": 3, "install_date": "2024-11-02", "cost": 7200.0}
    r = await flow.async_configure(r["flow_id"], {"units": 3, "install_date": "2024-11-02", "cost": 7200})

    # Batteries added later: the second group gets the "_2" date and cost
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "store_search"})
    r = await flow.async_configure(r["flow_id"], {"brand": "Sungrow"})
    r = await flow.async_configure(r["flow_id"], {"series": "Sungrow|SBR"})
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sungrow-sbr-battery-module-3-2-kwh-au"]})
    suggested = {str(k): k.description["suggested_value"] for k in r["data_schema"].schema
                 if k.description and "suggested_value" in k.description}
    assert suggested == {"install_date": "2025-06-01", "cost": 2400.0}


async def test_detect_huawei_counts_packs_from_serials(hass: HomeAssistant):
    """wlcrs: packs with a serial number are counted; 20.7 kWh over 3 packs = LUNA2000-7-S1."""
    sn = "HV1111111111"
    ents = [RegistryEntity(f"sensor.batteries_{k}", "huawei_solar", f"{sn}_storage_{k}")
            for k in ("total_discharge", "total_charge", "rated_capacity")]
    ents += [RegistryEntity(f"sensor.battery_1_pack_{n}_serial_number", "huawei_solar",
                            f"{sn}_storage_unit_1_battery_pack_{n}_serial_number") for n in (1, 2, 3)]
    _register(hass, ents, owner_domain="huawei_solar")
    hass.states.async_set("sensor.batteries_rated_capacity", "20700", {"unit_of_measurement": "Wh"})
    for n, serial in ((1, "PACKSERIAL1"), (2, "PACKSERIAL2"), (3, "PACKSERIAL3")):
        hass.states.async_set(f"sensor.battery_1_pack_{n}_serial_number", serial)
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    r = await flow.async_configure(r["flow_id"], {"system": "huawei-solar-wlcrs|default"})
    assert r["step_id"] == "group" and r["description_placeholders"]["name"] == "Huawei LUNA2000-7-S1"
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert units_key.description["suggested_value"] == 3

    # An empty third position: 2 packs, 13.8 kWh
    hass.states.async_set("sensor.batteries_rated_capacity", "13.8", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.battery_1_pack_3_serial_number", "")
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    r = await flow.async_configure(r["flow_id"], {"system": "huawei-solar-wlcrs|default"})
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert units_key.description["suggested_value"] == 2


async def test_nothing_detected_goes_to_store_search(hass: HomeAssistant):
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    assert r["step_id"] == "detect_none"
    r = await flow.async_configure(r["flow_id"], {})
    assert r["step_id"] == "store_search"


async def test_options_add_group_prefills_energy_manager_second_battery(hass: HomeAssistant):
    """Options → Battery groups → Add: the second group is pre-filled from Energy Manager's
    battery_install_date_2 / battery_install_cost_2 helpers, and the spec is copied into the group."""
    from custom_components.battery_ledger.const import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION
    from custom_components.battery_ledger.store_client import async_get_store_index
    ents = em_entities() + [
        RegistryEntity("input_datetime.battery_install_date_2", "input_datetime", "battery_install_date_2"),
        RegistryEntity("input_number.battery_install_cost_2", "input_number", "battery_install_cost_2"),
    ]
    _register(hass, [e for e in ents if e.platform == "mqtt"], owner_domain="mqtt")
    _register(hass, [e for e in ents if e.platform != "mqtt"])
    hass.states.async_set("input_datetime.battery_install_date_2", "2025-06-01")
    hass.states.async_set("input_number.battery_install_cost_2", "2400.0")
    charged = "sensor.inverter_total_battery_charge"
    hass.states.async_set(charged, "500", {"unit_of_measurement": "kWh"})

    index = await async_get_store_index(hass)
    spec_id = "sungrow-sbr-battery-module-3-2-kwh-au"
    spec = index.get(spec_id)
    entry = MockConfigEntry(domain=DOMAIN, title="Sungrow", version=CONFIG_ENTRY_VERSION,
                            minor_version=CONFIG_ENTRY_MINOR_VERSION,
                            data={"name": "Sungrow", "charged_energy_entity": charged,
                                  "groups": [{"spec": spec, "units": 3, "install_date": "2024-11-02"}]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    opts = hass.config_entries.options
    r = await opts.async_init(entry.entry_id)
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "groups"})
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "group_add"})
    assert r["step_id"] == "group_add"
    [key] = list(r["data_schema"].schema)
    first = key and r["data_schema"].schema[key].config["options"][0]["label"]
    assert first.startswith("Sungrow")  # the setup's brand first
    r = await opts.async_configure(r["flow_id"], {"spec": spec_id})
    assert r["step_id"] == "group_add_details"
    suggested = {str(k): k.description["suggested_value"] for k in r["data_schema"].schema
                 if k.description and "suggested_value" in k.description}
    assert suggested == {"install_date": "2025-06-01", "cost": 2400.0}
    r = await opts.async_configure(r["flow_id"], {"units": 3, "install_date": "2025-06-01", "cost": 2400})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    new = entry.data["groups"][1]
    assert (new["units"], new["install_date"], new["cost"], new["spec"]["id"]) == (3, "2025-06-01", 2400, spec_id)


async def _module_entry(hass: HomeAssistant):
    """sigenergy2mqtt setup tracking SERIALS[0] individually; SERIALS[1] has since been added to the stack."""
    from custom_components.battery_ledger.const import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION
    from custom_components.battery_ledger.store_client import async_get_store_index
    _register(hass, mqtt_entities(), owner_domain="mqtt")
    for sn in SERIALS:
        hass.states.async_set(f"sensor.sigen_0_cloud_4_{sn}_rated_battery_capacity", "8.06", {"unit_of_measurement": "kWh"})
        hass.states.async_set(f"sensor.sigen_0_cloud_4_{sn}_total_discharge_amount", "100", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.sigen_0_accumulated_discharge_energy", "300", {"unit_of_measurement": "kWh"})
    spec = (await async_get_store_index(hass)).get("sigenergy-sigenstor-bat-8-0-anz")
    sn = SERIALS[0]
    entry = MockConfigEntry(domain=DOMAIN, title="Sigen", version=CONFIG_ENTRY_VERSION,
                            minor_version=CONFIG_ENTRY_MINOR_VERSION, data={
        "name": "Sigen", "sensor_profile": "sigenergy2mqtt",
        "discharged_energy_entity": "sensor.sigen_0_accumulated_discharge_energy",
        "groups": [{"spec": spec, "units": 1, "install_date": "2024-01-01"}],
        "modules": [{"id": sn, "group": 0, "discharged_entity": f"sensor.sigen_0_cloud_4_{sn}_total_discharge_amount",
                     "soc_entity": f"sensor.sigen_0_cloud_4_{sn}_battery_soc"}]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_options_more_units_offers_new_modules(hass: HomeAssistant):
    """Modules added to a stack: raising the group's units offers the newly reported module sensors."""
    entry = await _module_entry(hass)
    opts = hass.config_entries.options
    r = await opts.async_init(entry.entry_id)
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "groups"})
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "group_pick"})
    r = await opts.async_configure(r["flow_id"], {"units": 2, "install_date": "2024-01-01"})
    assert r["step_id"] == "group_modules"
    ph = r["description_placeholders"]
    assert (ph["count"], ph["found"], ph["units"]) == ("1", "2", "2") and f"{SERIALS[1]}: 8.06 kWh ✓" in ph["modules"]
    [key] = list(r["data_schema"].schema)
    assert key.default() is True
    r = await opts.async_configure(r["flow_id"], {"use_modules": True})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert sorted((m["id"], m["group"]) for m in entry.data["modules"]) == [(SERIALS[0], 0), (SERIALS[1], 0)]
    assert entry.data["groups"][0]["units"] == 2


async def test_options_add_group_new_module_other_model(hass: HomeAssistant):
    """A module whose rated capacity doesn't match the added group's model isn't assigned to it."""
    entry = await _module_entry(hass)
    opts = hass.config_entries.options
    r = await opts.async_init(entry.entry_id)
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "groups"})
    r = await opts.async_configure(r["flow_id"], {"next_step_id": "group_add"})
    r = await opts.async_configure(r["flow_id"], {"spec": "sigenergy-sigenstor-bat-10-0-anz"})
    r = await opts.async_configure(r["flow_id"], {"units": 1, "install_date": "2025-01-01"})
    assert r["step_id"] == "group_modules" and f"{SERIALS[1]}: 8.06 kWh ✗" in r["description_placeholders"]["modules"]
    [key] = list(r["data_schema"].schema)
    assert key.default() is False
    r = await opts.async_configure(r["flow_id"], {"use_modules": True})
    await hass.async_block_till_done()
    assert [(m["id"], m["group"]) for m in entry.data["modules"]] == [(SERIALS[0], 0)]
    assert len(entry.data["groups"]) == 2


async def _huawei_two_towers(hass: HomeAssistant):
    """wlcrs: one SUN2000-5KTL-L1 with two towers of 3 × 5 kWh (storage units 1 and 2), 30 kWh in all."""
    from homeassistant.helpers import device_registry as dr
    sn = "HV2222222222"
    owner = MockConfigEntry(domain="huawei_solar")
    owner.add_to_hass(hass)
    devices = dr.async_get(hass)
    inverter = devices.async_get_or_create(config_entry_id=owner.entry_id, identifiers={("huawei_solar", sn)},
                                           name="Inverter 1", model="SUN2000-5KTL-L1")
    batteries = devices.async_get_or_create(config_entry_id=owner.entry_id, identifiers={("huawei_solar", f"{sn}_b")},
                                            name="Batteries", model="Batteries", via_device=("huawei_solar", sn))
    registry = er.async_get(hass)
    for k in ("total_discharge", "total_charge", "rated_capacity"):
        registry.async_get_or_create("sensor", "huawei_solar", f"{sn}_storage_{k}", suggested_object_id=f"batteries_{k}",
                                     config_entry=owner, device_id=batteries.id)
    for unit in (1, 2):
        for n in (1, 2, 3):
            oid = f"battery_{unit}_pack_{n}_serial_number"
            registry.async_get_or_create("sensor", "huawei_solar", f"{sn}_storage_unit_{unit}_battery_pack_{n}_serial_number",
                                         suggested_object_id=oid, config_entry=owner)
            hass.states.async_set(f"sensor.{oid}", f"PACK{unit}{n}")
    hass.states.async_set("sensor.batteries_rated_capacity", "30000", {"unit_of_measurement": "Wh"})
    assert inverter.model == "SUN2000-5KTL-L1"
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    return await flow.async_configure(r["flow_id"], {"system": "huawei-solar-wlcrs|default"})


async def test_detect_huawei_towers_installed_separately(hass: HomeAssistant):
    """A tower added later, of another brand: one battery group per tower, each model chosen."""
    r = await _huawei_two_towers(hass)
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "detect_towers"
    assert r["description_placeholders"]["towers"] == (
        "- 1 · SUN2000-5KTL-L1 · 1: 3 × 5 kWh\n- 1 · SUN2000-5KTL-L1 · 2: 3 × 5 kWh")
    flow = hass.config_entries.flow
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect_separate"})
    assert r["step_id"] == "detect_tower" and r["description_placeholders"]["number"] == "1"
    ids = [o["value"] for o in r["data_schema"].schema["spec"].config["options"]]
    assert set(ids) == {"huawei-luna2000-5-s0-au", "istore-is-batt-5000-es-au"}
    r = await flow.async_configure(r["flow_id"], {"spec": "huawei-luna2000-5-s0-au"})
    assert r["step_id"] == "detect_tower" and r["description_placeholders"]["place"] == "1 · SUN2000-5KTL-L1 · 2"
    r = await flow.async_configure(r["flow_id"], {"spec": "istore-is-batt-5000-es-au"})
    assert r["step_id"] == "group" and r["description_placeholders"]["name"] == "Huawei LUNA2000-5-S0"
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert units_key.description["suggested_value"] == 3
    r = await flow.async_configure(r["flow_id"], {"units": 3, "install_date": "2022-03-01"})
    assert r["step_id"] == "group" and r["description_placeholders"]["name"].startswith("iStore")
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert units_key.description["suggested_value"] == 3


async def test_detect_huawei_towers_installed_together(hass: HomeAssistant):
    """Installed together: as before, the fitting models are listed for the user to tick."""
    r = await _huawei_two_towers(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "detect_together"})
    assert r["step_id"] == "store_select"
    ids = {o["value"] for o in r["data_schema"].schema["spec_ids"].config["options"]}
    assert ids == {"huawei-luna2000-5-s0-au", "istore-is-batt-5000-es-au"}


async def test_detect_sigenergy2mqtt_two_inverters(hass: HomeAssistant):
    """sigenergy2mqtt with Cloud modules on two inverters: the modules don't say which inverter they're on, so
    each inverter's rated battery capacity is used to ask whether the stacks went in together."""
    ents = mqtt_entities() + [
        RegistryEntity(f"sensor.sigen_0_inverter_{n}_{k}", "mqtt", f"sigen_0_00{n}_{reg}")
        for n in (1, 2) for k, reg in (("rated_battery_capacity", 30548), ("model", 30500))]
    _register(hass, ents, owner_domain="mqtt")
    for n, kwh in ((1, "48.36"), (2, "32.24")):
        hass.states.async_set(f"sensor.sigen_0_inverter_{n}_rated_battery_capacity", kwh, {"unit_of_measurement": "kWh"})
        hass.states.async_set(f"sensor.sigen_0_inverter_{n}_model", "SigenStor EC 30.0 TP AU")
    for sn in SERIALS:
        hass.states.async_set(f"sensor.sigen_0_cloud_4_{sn}_rated_battery_capacity", "8.06", {"unit_of_measurement": "kWh"})
    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect"})
    r = await flow.async_configure(r["flow_id"], {"system": "sigenergy2mqtt|prefix=sigen|plant=0"})
    assert r["step_id"] == "detect_towers"
    assert r["description_placeholders"]["towers"] == (
        "- 1 · SigenStor EC 30.0 TP AU · –: 6 × 8.06 kWh\n- 2 · SigenStor EC 30.0 TP AU · –: 4 × 8.06 kWh")
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "detect_separate"})
    assert r["step_id"] == "group" and r["description_placeholders"]["name"] == "Sigenergy SigenStor BAT 8.0"
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert units_key.description["suggested_value"] == 6
    r = await flow.async_configure(r["flow_id"], {"units": 6, "install_date": "2024-01-01"})
    units_key = next(k for k in r["data_schema"].schema if str(k) == "units")
    assert r["step_id"] == "group" and units_key.description["suggested_value"] == 4


async def test_import_keeps_module_groups_by_serial(hass: HomeAssistant, tmp_path):
    """Two groups of the same model: capacity can't tell their modules apart, the saved serials can."""
    from contextlib import contextmanager
    from unittest.mock import patch

    from custom_components.battery_ledger.backup import async_export_file
    entry = await _module_entry(hass)
    spec = entry.data["groups"][0]["spec"]
    sn0, sn1 = SERIALS
    hass.config_entries.async_update_entry(entry, data={
        **entry.data,
        "groups": [{"spec": spec, "units": 1, "install_date": "2024-01-01"},
                   {"spec": spec, "units": 1, "install_date": "2025-01-01"}],
        "modules": [{**entry.data["modules"][0]},
                    {"id": sn1, "group": 1, "discharged_entity": f"sensor.sigen_0_cloud_4_{sn1}_total_discharge_amount",
                     "soc_entity": None}]})
    await hass.async_block_till_done()
    _name, text = await async_export_file(hass, entry)
    upload = tmp_path / "setup.json"
    upload.write_text(text)

    @contextmanager
    def uploaded(_hass, _file_id):
        yield upload

    flow = hass.config_entries.flow
    r = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "import_setup"})
    with patch("custom_components.battery_ledger.config_flow.process_uploaded_file", uploaded):
        r = await flow.async_configure(r["flow_id"], {"file": "0123456789abcdef0123456789abcdef"})
    assert r["step_id"] == "sensors"
    key = next(iter(r["data_schema"].schema))
    assert key.default().startswith("sigenergy2mqtt")  # the saved setup's integration
    r = await flow.async_configure(r["flow_id"], {"integration": key.default()})
    assert r["step_id"] == "modules"
    per_group = r["description_placeholders"]["per_group"]
    assert per_group.count("1 / 1 ✓") == 2
    [use] = list(r["data_schema"].schema)
    assert use.default() is True
    r = await flow.async_configure(r["flow_id"], {"use_modules": True})
    r = await flow.async_configure(r["flow_id"], {"name": "Sigen 2", "currency_style": "symbol",
                                                  "discharged_energy_entity": "sensor.sigen_0_accumulated_discharge_energy"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert sorted((m["id"], m["group"]) for m in r["result"].data["modules"]) == [(sn0, 0), (sn1, 1)]
