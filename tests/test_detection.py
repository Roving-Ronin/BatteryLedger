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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.battery_ledger.const import DOMAIN
from custom_components.battery_ledger.detect import RegistryEntity, assign_modules, detect

SNAPSHOT = Path(__file__).resolve().parent.parent / "custom_components" / "battery_ledger" / "data" / "index_snapshot.json"
PROFILES = {p["id"]: p for p in json.loads(SNAPSHOT.read_text())["profiles"]}
TYP_ENTRY = "01JCX4ZQ8T5V2M3N4P5Q6R7S8T"
STATION = "203840556"
SERIALS = ["110b13641026", "110b13641048"]




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

    r = await flow.async_configure(r["flow_id"], {"name": "Sigen", "cost": 9000, **suggested})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

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
    # Without an EMMA, three inverters' totals are ambiguous, so nothing is detected (sensors are chosen manually)
    assert detect(PROFILES["huawei-solar-wlcrs"], ents) == []
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
