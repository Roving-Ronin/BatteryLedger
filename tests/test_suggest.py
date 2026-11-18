"""Battery model and unit suggestions from what an integration reports (pure)."""

import json
from pathlib import Path

from custom_components.battery_ledger.suggest import Reading, narrow_by_model, suggest

INDEX = json.loads((Path(__file__).parents[1] / "custom_components/battery_ledger/data/index_snapshot.json").read_text())
SPECS = INDEX["specs"]


def brand(*names):
    return [s for s in SPECS if s["brand"] in names]


def ids(specs):
    return [s["id"] for s in specs]


def test_sigen_pack_count_and_model_type():
    """48.36 kWh over 6 packs = 8.06 per module: BAT 8.0, decided."""
    r = suggest(brand("Sigenergy"), [Reading(48.36, 6, "SigenStor EC 30.0 TP AU")])
    assert [(s["id"], n) for s, n in r.groups] == [("sigenergy-sigenstor-bat-8-0-anz", 6)]


def test_sigen_model_type_separates_neo():
    """BAT 6.0 and Neo BAT 6.0 are both 6.02 kWh: the inverter model decides, or the user does."""
    neo, stor = "sigenergy-sigenstor-neo-bat-6-0-anz", "sigenergy-sigenstor-bat-6-0-anz"
    assert ids(narrow_by_model(brand("Sigenergy"), "SigenStor EC 10.0 TP AU")).count(neo) == 0
    r = suggest(brand("Sigenergy"), [Reading(18.06, 3, "SigenStor EC 10.0 TP AU")])
    assert [(s["id"], n) for s, n in r.groups] == [(stor, 3)]
    r = suggest(brand("Sigenergy"), [Reading(18.06, 3, None)])
    assert not r.decided and set(ids(r.candidates)) == {neo, stor} and r.units == {neo: 3, stor: 3}


def test_capacity_alone_can_be_ambiguous():
    """24.18 kWh: 3 x BAT 8.0 or 4 x BAT 6.0 (24.08) — offered as a choice with units."""
    r = suggest(brand("Sigenergy"), [Reading(24.18)])
    assert not r.decided
    assert r.units["sigenergy-sigenstor-bat-8-0-anz"] == 3 and r.units["sigenergy-sigenstor-bat-6-0-anz"] == 4


def test_two_inverters_beyond_the_per_inverter_limit():
    """6 modules on each of two inverters: two groups of 6 (the spec allows 6 per inverter)."""
    r = suggest(brand("Sigenergy"), [Reading(48.36, 6), Reading(48.36, 6)])
    assert [(s["id"], n) for s, n in r.groups] == [("sigenergy-sigenstor-bat-8-0-anz", 6)] * 2
    r = suggest(brand("Sigenergy"), [Reading(24.18, 3), Reading(16.12, 2)])
    assert [(s["id"], n) for s, n in r.groups] == [("sigenergy-sigenstor-bat-8-0-anz", 5)]


def test_sungrow_capacity_only():
    assert [(s["id"], n) for s, n in suggest(brand("Sungrow"), [Reading(9.6)]).groups] == [
        (s["id"], 3) for s in SPECS if s["model"].startswith("SBR")]
    assert [(s["model"], n) for s, n in suggest(brand("Sungrow"), [Reading(25.0)]).groups] == [
        ("SBH Battery Module 5.0 kWh", 5)]
    assert suggest(brand("Sungrow"), [Reading(11.0)]).groups == []  # fits neither


def test_rebadged_luna():
    """S1 (identical figures): shown as detected. S0 (iStore's warranty differs): the user picks."""
    r = suggest(brand("Huawei", "iStore"), [Reading(20.7, 3)])
    assert [(s["model"], n) for s, n in r.groups] == [("LUNA2000-7-S1", 3)]
    r = suggest(brand("Huawei", "iStore"), [Reading(15.0, 3)])
    assert sorted(s["model"] for s in r.candidates) == ["IS-BATT-5000-ES", "LUNA2000-5-S0"]


def test_per_module_readings():
    """sigenergy2mqtt: one reading per module, two models in one system."""
    r = suggest(brand("Sigenergy"), [Reading(module_kwh=[8.06]), Reading(module_kwh=[8.06]),
                                     Reading(module_kwh=[9.04])])
    assert sorted((s["model"], n) for s, n in r.groups) == [("SigenStor BAT 10.0", 1), ("SigenStor BAT 8.0", 2)]


def test_byd_towers():
    """Two HVS towers of 4 modules: 2.56 kWh each, a group per tower (the table is per tower)."""
    r = suggest(brand("BYD"), [Reading(10.24, 4), Reading(10.24, 4)])
    assert [(s["model"], n) for s, n in r.groups] == [("HVS module 2.56 kWh", 4)] * 2


def test_nothing_to_go_on():
    assert not suggest(brand("Sigenergy"), []).decided
    assert suggest(brand("Sigenergy"), [Reading(None)]).candidates == []
