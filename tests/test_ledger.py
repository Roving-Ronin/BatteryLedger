"""Tests for the pure calculation module. Run from repo root: pytest -q tests"""

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "battery_ledger"
_spec = importlib.util.spec_from_file_location("ledger", COMPONENT / "ledger.py")
ledger = importlib.util.module_from_spec(_spec)
sys.modules["ledger"] = ledger
_spec.loader.exec_module(ledger)

SPECS = {s["id"]: s for s in json.loads((COMPONENT / "data" / "index_snapshot.json").read_text())["specs"]}
BAT8 = SPECS["sigenergy-sigenstor-bat-8-0-anz"]
BAT10 = SPECS["sigenergy-sigenstor-bat-10-0-anz"]
TODAY = date(2026, 11, 17)


def test_matches_existing_template_figures():
    """6 x BAT 8.0, numbers from the current YAML package's dashboard."""
    used = 142620 - 127735  # rated - remaining = charged energy so far
    install = TODAY - timedelta(days=487)
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 6, install)], today=TODAY,
        charged_kwh=used, cost=26062.0, reported_capacity_kwh=48.36))
    assert res.limit_kwh == pytest.approx(142620)
    assert res.remaining_kwh == pytest.approx(127735)
    assert res.used_pct == pytest.approx(10.44, abs=0.01)
    assert res.cost_per_kwh_rated == pytest.approx(0.1827, abs=0.0001)
    assert res.cost_consumed == pytest.approx(2719.5, abs=1)
    assert res.initial_usable_kwh == pytest.approx(46.8)
    # Age-driven: 487 days of a 10-year warranty, 30% capacity allowance
    assert res.driver == ledger.DRIVER_AGE
    assert res.floor_pct == pytest.approx(100 - 30 * 487 / 3652.5, abs=0.05)
    assert res.status == ledger.STATUS_ON_TRACK
    assert res.hardware == ledger.HW_MATCH
    # Warranty counts discharged energy; with only a charged sensor it falls back and says so
    assert res.groups[0].basis_used == "charged"
    assert ledger.NOTE_NO_DISCHARGED_SENSOR in res.notes


def test_projected_capped_at_warranty():
    install = TODAY - timedelta(days=100)
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 2, install)], today=TODAY, charged_kwh=20000, cost=10000))
    assert res.projected_kwh == pytest.approx(res.limit_kwh)
    assert res.status == ledger.STATUS_AHEAD and res.driver == ledger.DRIVER_THROUGHPUT
    assert res.cost_per_kwh_projected == pytest.approx(res.cost_per_kwh_rated)


def test_expired_by_throughput():
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 1, TODAY - timedelta(days=400))], today=TODAY,
        charged_kwh=30000, cost=5000))
    assert res.status == ledger.STATUS_EXPIRED
    assert res.floor_pct == pytest.approx(70)
    assert res.remaining_kwh == 0
    assert res.remaining_value == pytest.approx(0)


def test_bat6_figures():
    bat6 = SPECS["sigenergy-sigenstor-bat-6-0-anz"]
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(bat6, 3, TODAY)], today=TODAY, discharged_kwh=0,
        reported_capacity_kwh=18.06))
    assert res.limit_kwh == pytest.approx(3 * 17790)
    assert res.initial_usable_kwh == pytest.approx(3 * 5.84)
    assert res.hardware == ledger.HW_MATCH


def test_mixed_groups_split_by_capacity_and_age():
    old = ledger.GroupInput(BAT8, 2, TODAY - timedelta(days=730))
    new = ledger.GroupInput(BAT10, 1, TODAY - timedelta(days=365))
    res = ledger.compute(ledger.LedgerInput(groups=[old, new], today=TODAY, charged_kwh=10000))
    w_old, w_new = 7.8 * 2 * 730, 8.76 * 365
    assert res.groups[0].used_kwh == pytest.approx(10000 * w_old / (w_old + w_new))
    assert res.limit_kwh == pytest.approx(23770 * 2 + 26680)
    assert sum(g.used_kwh for g in res.groups) == pytest.approx(10000)
    assert ledger.NOTE_SPLIT_ESTIMATE in res.notes


def test_unspecified_basis_prefers_charged():
    spec = json.loads(json.dumps(BAT8))
    spec["warranty"]["throughput"]["basis"] = "unspecified"
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(spec, 1, TODAY - timedelta(days=10))], today=TODAY,
        charged_kwh=1000, discharged_kwh=900))
    assert res.used_kwh == pytest.approx(1000)
    assert ledger.NOTE_BASIS_UNSTATED_CHARGED in res.notes


def test_discharged_basis_uses_discharged_sensor():
    spec = BAT8
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(spec, 1, TODAY - timedelta(days=10))], today=TODAY,
        charged_kwh=1000, discharged_kwh=900))
    assert res.used_kwh == pytest.approx(900)
    assert res.notes == []


def test_table_scope_and_unit_limits():
    spec = json.loads(json.dumps(BAT8))
    spec["warranty"]["throughput"] = {"basis": "charged", "scope": "table",
                                      "table": [{"units": 2, "kwh": 40000}, {"units": 3, "kwh": 55000}]}
    assert ledger.throughput_limit_kwh(spec, 3) == 55000
    with pytest.raises(ledger.SpecError, match="no entry for 4"):
        ledger.validate_units(spec, 4)
    with pytest.raises(ledger.SpecError, match="maximum"):
        ledger.validate_units(BAT8, 7)


def test_hardware_mismatch_and_no_cost():
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 6, TODAY)], today=TODAY, charged_kwh=0,
        reported_capacity_kwh=40.3))
    assert res.hardware == ledger.HW_MISMATCH
    assert res.cost_per_kwh_rated is None and res.remaining_value is None
    assert res.low_confidence and res.avg_daily_kwh is None


def test_per_module_worst_module_drives_status():
    mods = {"A": 1000.0, "B": 1200.0, "C": 5000.0}
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 3, TODAY - timedelta(days=365), module_kwh=mods)],
        today=TODAY, discharged_kwh=7300, module_soc={"A": 55.0, "B": 57.5, "C": 49.0},
        reported_soh_pct=99.0))
    g = res.groups[0]
    assert g.source == "modules"
    assert res.used_kwh == pytest.approx(7200)
    assert res.worst_module_id == "C"
    assert res.worst_module_pct == pytest.approx(5000 / 23770 * 100, abs=0.01)
    # Module C: 21% of its limit after 10% of the time -> throughput-driven, ahead of time
    assert res.driver == ledger.DRIVER_THROUGHPUT and res.status == ledger.STATUS_AHEAD
    assert res.module_vs_plant_pct == pytest.approx(7200 / 7300 * 100)
    assert res.soc_spread == pytest.approx(8.5)
    assert res.health_margin == pytest.approx(99.0 - res.floor_pct)


def test_incomplete_modules_fall_back_to_plant():
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 3, TODAY - timedelta(days=100), module_kwh={"A": 10.0, "B": 10.0})],
        today=TODAY, discharged_kwh=500))
    assert res.groups[0].source == "plant"
    assert res.used_kwh == pytest.approx(500)
    assert f"{ledger.NOTE_MODULES_NOT_USED}:{BAT8['id']}:2/3" in res.notes


def test_mixed_module_and_plant_groups():
    """Module-measured group is subtracted from the plant counter before allocating the rest."""
    a = ledger.GroupInput(BAT8, 2, TODAY - timedelta(days=200), module_kwh={"A": 300.0, "B": 400.0})
    b = ledger.GroupInput(BAT10, 1, TODAY - timedelta(days=200))
    res = ledger.compute(ledger.LedgerInput(groups=[a, b], today=TODAY, discharged_kwh=1000))
    assert res.groups[0].used_kwh == pytest.approx(700)
    assert res.groups[1].used_kwh == pytest.approx(300)
    assert res.module_vs_plant_pct is None
    assert ledger.NOTE_SPLIT_ESTIMATE not in res.notes


def test_modules_only_without_plant_sensor():
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 1, TODAY - timedelta(days=10), module_kwh={"A": 50.0})],
        today=TODAY))
    assert res.used_kwh == pytest.approx(50)
