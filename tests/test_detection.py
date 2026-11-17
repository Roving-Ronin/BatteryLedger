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
    r = await flow.async_configure(r["flow_id"], {"spec_ids": ["sigenergy-sigenstor-bat-8-0-anz"]})
    install = (dt_util.now().date() - timedelta(days=365)).isoformat()
    r = await flow.async_configure(r["flow_id"], {"units": 2, "install_date": install})
    r = await flow.async_configure(r["flow_id"], {"next_step_id": "sensors"})
    assert r["step_id"] == "sensors"
    options = r["data_schema"].schema["integration"].config["options"]
    values = [o["value"] for o in options]
    assert "sigenergy2mqtt|prefix=sigen|plant=0" in values
    assert "sigen-local-modbus|none" in values  # listed, but not installed

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
