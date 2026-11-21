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
        groups=[ledger.GroupInput(BAT8, 6, install, cost=26062.0)], today=TODAY,
        charged_kwh=used, reported_capacity_kwh=48.36))
    assert res.limit_kwh == pytest.approx(142620)
    assert res.remaining_kwh == pytest.approx(127735)
    assert res.used_pct == pytest.approx(10.44, abs=0.01)
    assert res.cost_per_kwh_rated == pytest.approx(0.1827, abs=0.0001)
    # Cost follows the warranty driver (age here): 487 days of a 10-year warranty
    assert res.cost_consumed == pytest.approx(26062 * 487 / 3652.5, abs=0.01)
    assert res.remaining_value == pytest.approx(26062 - res.cost_consumed)
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
        groups=[ledger.GroupInput(BAT8, 2, install, cost=10000)], today=TODAY, charged_kwh=20000))
    assert res.projected_kwh == pytest.approx(res.limit_kwh)
    assert res.status == ledger.STATUS_AHEAD and res.driver == ledger.DRIVER_THROUGHPUT
    assert res.cost_per_kwh_projected == pytest.approx(res.cost_per_kwh_rated)
    # Throughput-driven: cost follows the throughput share
    assert res.cost_consumed == pytest.approx(10000 * res.groups[0].throughput_fraction)
    # 20,000 kWh in 100 days: the 47,540 kWh limit is reached in about 238 days, long before 10 years
    g = res.groups[0]
    assert g.usage_end == install + timedelta(days=round(g.limit_kwh / 200))
    assert g.usage_end < g.warranty_end
    assert g.as_attributes()["throughput_end_date"] == g.usage_end.isoformat()


def test_expired_by_throughput():
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 1, TODAY - timedelta(days=400), cost=5000)], today=TODAY,
        charged_kwh=30000))
    assert res.status == ledger.STATUS_EXPIRED
    assert res.floor_pct == pytest.approx(70)
    assert res.remaining_kwh == 0
    assert res.remaining_value == pytest.approx(0) and res.cost_consumed == pytest.approx(5000)


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


def test_cycles_per_day_matches_yaml_formula():
    """YAML: discharged / age_days / capacity; projected = cycles x capacity x warranty days."""
    days, discharged, rated = 487, 14886.0, 48.36
    spec = BAT8  # discharged basis
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(spec, 6, TODAY - timedelta(days=days))], today=TODAY,
        discharged_kwh=discharged, reported_capacity_kwh=rated))
    assert res.cycles_per_day == pytest.approx(discharged / days / rated)
    assert res.projected_kwh == pytest.approx(res.cycles_per_day * rated * 10 * 365.25)
    # Without a rated capacity sensor, the spec's reported capacity x units is used
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(spec, 6, TODAY - timedelta(days=days))], today=TODAY, discharged_kwh=discharged))
    assert res.cycles_per_day == pytest.approx(discharged / days / (8.06 * 6))


def test_cost_per_group():
    """Batteries added later carry their own cost on their own warranty clock."""
    first = ledger.GroupInput(BAT8, 4, TODAY - timedelta(days=1461), cost=20000)  # 4 years in
    added = ledger.GroupInput(BAT8, 2, TODAY - timedelta(days=365), cost=8000)    # 1 year in
    res = ledger.compute(ledger.LedgerInput(groups=[first, added], today=TODAY, charged_kwh=1000))
    g1, g2 = res.groups
    assert g1.cost_consumed == pytest.approx(20000 * g1.life_fraction)
    assert g2.cost_consumed == pytest.approx(8000 * g2.life_fraction)
    assert res.cost_consumed == pytest.approx(g1.cost_consumed + g2.cost_consumed)
    assert res.remaining_value == pytest.approx(28000 - res.cost_consumed)
    assert res.cost_per_kwh_rated == pytest.approx(28000 / res.limit_kwh)
    assert g1.as_attributes()["cost"] == 20000 and g2.as_attributes()["cost_consumed"] is not None

    # Each group's own financials, for the card's group switcher
    assert g1.remaining_value == pytest.approx(20000 - g1.cost_consumed)
    assert g1.cost_per_kwh_rated == pytest.approx(20000 / g1.limit_kwh)
    assert g2.cost_per_kwh_rated == pytest.approx(8000 / g2.limit_kwh)
    assert g1.cost_per_kwh_projected == pytest.approx(20000 / g1.projected_kwh)
    assert g1.export_basis in ("age", "usage") and g1.cost_per_kwh_export is not None
    assert g2.as_attributes()["remaining_value"] == pytest.approx(8000 - g2.cost_consumed, abs=0.01)


def test_group_financials_match_the_group_alone():
    """A group's own figures are what the setup shows when that group is its only battery."""
    first = ledger.GroupInput(BAT8, 4, TODAY - timedelta(days=1461), cost=20000)
    added = ledger.GroupInput(BAT8, 2, TODAY - timedelta(days=365), cost=8000)
    both = ledger.compute(ledger.LedgerInput(groups=[first, added], today=TODAY, charged_kwh=3000,
                                             export_setting="cheapest"))
    alone = ledger.compute(ledger.LedgerInput(groups=[added], today=TODAY, charged_kwh=both.groups[1].used_kwh,
                                              export_setting="cheapest"))
    g2 = both.groups[1]
    assert g2.remaining_value == pytest.approx(alone.remaining_value)
    assert g2.cost_per_kwh_rated == pytest.approx(alone.cost_per_kwh_rated)
    assert g2.cost_per_kwh_projected == pytest.approx(alone.cost_per_kwh_projected)
    assert g2.cost_per_kwh_export == pytest.approx(alone.cost_per_kwh_export)
    assert g2.export_basis == alone.export_basis


def test_cost_only_on_some_groups():
    """Groups without a cost are left out of the cost figures, not counted as free."""
    first = ledger.GroupInput(BAT8, 4, TODAY - timedelta(days=365), cost=20000)
    added = ledger.GroupInput(BAT10, 2, TODAY - timedelta(days=100))
    res = ledger.compute(ledger.LedgerInput(groups=[first, added], today=TODAY, charged_kwh=1000))
    assert res.cost_consumed == pytest.approx(res.groups[0].cost_consumed)
    assert res.cost_per_kwh_rated == pytest.approx(20000 / res.groups[0].limit_kwh)
    assert res.groups[1].cost is None and res.groups[1].as_attributes()["cost"] is None
    none = ledger.compute(ledger.LedgerInput(groups=[ledger.GroupInput(BAT8, 1, TODAY)], today=TODAY, charged_kwh=0))
    assert none.cost_consumed is None and none.remaining_value is None and none.cost_per_kwh_rated is None


def test_usage_end_needs_a_limit_and_use():
    unused = ledger.compute(ledger.LedgerInput(groups=[ledger.GroupInput(BAT8, 1, TODAY - timedelta(days=10))],
                                               today=TODAY, charged_kwh=0))
    assert unused.groups[0].usage_end is None
    slow = ledger.compute(ledger.LedgerInput(groups=[ledger.GroupInput(BAT8, 1, TODAY - timedelta(days=365))],
                                             today=TODAY, charged_kwh=365))
    assert slow.groups[0].usage_end > slow.groups[0].warranty_end  # 1 kWh a day: the date ends it first


def test_energy_counters_stuck_at_zero_are_flagged():
    """0 kWh after a month in service: a source that isn't reporting, flagged with a note code."""
    old = ledger.compute(ledger.LedgerInput(groups=[ledger.GroupInput(BAT8, 6, TODAY - timedelta(days=365))],
                                            today=TODAY, charged_kwh=0, discharged_kwh=0))
    assert ledger.NOTE_ENERGY_ZERO in old.notes
    new = ledger.compute(ledger.LedgerInput(groups=[ledger.GroupInput(BAT8, 6, TODAY - timedelta(days=10))],
                                            today=TODAY, charged_kwh=0, discharged_kwh=0))
    assert ledger.NOTE_ENERGY_ZERO not in new.notes  # just installed: 0 is plausible
    used = ledger.compute(ledger.LedgerInput(groups=[ledger.GroupInput(BAT8, 6, TODAY - timedelta(days=365))],
                                             today=TODAY, charged_kwh=5000, discharged_kwh=4800))
    assert ledger.NOTE_ENERGY_ZERO not in used.notes


def _export_case(days: int, daily_kwh: float, scope_kwh: float | None = 23770.0, **kw):
    from datetime import date, timedelta
    from custom_components.battery_ledger.ledger import GroupInput, LedgerInput, compute
    spec = {"brand": "X", "model": "Y", "capacity": {"unit": "module", "usable_kwh": 8.0, "nominal_kwh": 8.0},
            "warranty": {"years": 10, "eol_capacity_pct": 70,
                         "throughput": ({"scope": "per_unit", "kwh": scope_kwh, "basis": "discharged"}
                                        if scope_kwh else {"scope": "none", "basis": "discharged"})}}
    today = date(2026, 11, 19)
    return compute(LedgerInput(
        groups=[GroupInput(spec=spec, units=6, install_date=today - timedelta(days=days), cost=20000)],
        charged_kwh=None, discharged_kwh=days * daily_kwh, today=today, **kw))


def test_cost_per_kwh_export_warranty_basis_is_whichever_ends_first():
    # Age-driven (light use): age is higher than usage, and is the state
    age = _export_case(400, 10.0)
    assert age.export_basis == "age" and age.driver == "age"
    assert age.cost_per_kwh_export == pytest.approx(age.cost_per_kwh_projected)
    assert age.export_costs["usage"] == pytest.approx(age.cost_per_kwh_rated)
    assert age.export_costs["usage"] < age.cost_per_kwh_export
    # Usage-driven (heavy use): usage (rated) is higher than age
    use = _export_case(400, 60.0)
    assert use.export_basis == "usage" and use.cost_per_kwh_export == pytest.approx(use.cost_per_kwh_rated)
    assert use.export_costs["age"] < use.cost_per_kwh_export
    # Under 30 days: usage, whatever the setting
    early = _export_case(5, 2.0, export_setting="cheapest")
    assert early.export_basis == "usage" and early.low_confidence
    # Time-only warranty: age (uncapped)
    t = _export_case(400, 10.0, scope_kwh=None)
    assert t.cost_per_kwh_rated is None and t.export_basis == "age"
    assert t.cost_per_kwh_export == pytest.approx(20000 / (10.0 * 3652.5), rel=0.01)


def test_cost_per_kwh_export_estimated_service_life_and_cheapest():
    # ESL defaults to 15 years (this warranty is 10), spreading the cost over more throughput than by age
    default = _export_case(400, 10.0)
    assert default.esl_years == 15
    assert default.export_costs["esl"] == pytest.approx(default.export_costs["age"] * 10 / 15)
    g0 = default.groups[0]
    assert g0.as_attributes()["projected_throughput_kwh"] == round(g0.projected_kwh)  # for the card's group view
    # Estimated usage at EoSL: 10 kWh/day for 15 years, not capped at the warranted throughput
    assert default.projected_esl_kwh == pytest.approx(10.0 * 15 * 365.25)
    assert g0.as_attributes()["projected_esl_throughput_kwh"] == round(default.projected_esl_kwh)
    assert g0.eosl == g0.install_date.replace(year=g0.install_date.year + 15)
    # A warranty longer than 15 years is the default instead; a set ESL wins either way
    assert _export_case(400, 10.0, esl_years=12).esl_years == 12
    esl = _export_case(400, 10.0, esl_years=15, export_setting="esl")
    assert esl.export_basis == "esl"
    assert esl.cost_per_kwh_export == pytest.approx(esl.export_costs["age"] * 10 / 15)
    g = esl.groups[0]
    assert g.eosl == g.install_date.replace(year=g.install_date.year + 15) and esl.eosl == g.eosl
    # Cheapest: ESL beats the warranty; with an SoH trend of 25 years, that beats ESL
    cheap = _export_case(400, 10.0, esl_years=15, export_setting="cheapest")
    assert cheap.export_basis == "esl"
    soh = _export_case(400, 10.0, esl_years=15, export_setting="cheapest", soh_trend_years=25)
    assert soh.export_basis == "soh_trend" and soh.cost_per_kwh_export < cheap.cost_per_kwh_export
    # Heavy use, cheapest: the warranty's binding limit (usage) vs ESL; never the non-binding age figure
    heavy = _export_case(400, 60.0, export_setting="cheapest", esl_years=10)
    assert heavy.export_basis == "esl"  # 10 years uncapped < rated
    assert heavy.cost_per_kwh_export == pytest.approx(heavy.export_costs["age"])


def test_default_esl_years():
    from custom_components.battery_ledger.ledger import default_esl_years
    assert default_esl_years([{"warranty": {"years": 10}}]) == 15
    assert default_esl_years([{"warranty": {"years": 10}}, {"warranty": {"years": 20}}]) == 20


def test_cost_per_kwh_export_by_age_or_by_usage():
    # Age-driven battery: choosing by usage publishes the (lower) usage figure, by age the age figure
    usage = _export_case(400, 10.0, export_setting="usage")
    age = _export_case(400, 10.0, export_setting="age")
    assert usage.export_basis == "usage" and usage.cost_per_kwh_export == pytest.approx(usage.cost_per_kwh_rated)
    assert age.export_basis == "age" and age.cost_per_kwh_export > usage.cost_per_kwh_export
    # No throughput limit: by usage has no figure, so the warranty basis (age) is used
    t = _export_case(400, 10.0, scope_kwh=None, export_setting="usage")
    assert t.export_basis == "age"


def _roi_input(days, before=0.0, other=0.0, start=None):
    return ledger.RoiInput(total=sum(days.values()), days=days, before=before, other_costs=other, start=start)


def test_roi_from_daily_savings():
    """A year of $5 a day against $20,000 of batteries installed a year ago."""
    install = TODAY - timedelta(days=364)
    days = {install + timedelta(days=i): 5.0 for i in range(365)}
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 4, install, cost=20000)], today=TODAY, charged_kwh=4000,
        roi=_roi_input(days, before=0.0)))
    r = res.roi
    assert r.savings == 1825 and r.investment == 20000 and r.net_position == -18175
    assert r.roi_pct == pytest.approx(-90.9, abs=0.05) and r.daily_rate == 5 and r.confident
    assert r.days_to_go == 3635 and r.break_even == TODAY + timedelta(days=3635)
    assert r.today == 5 and r.this_week == 5 * (TODAY.weekday() + 1)
    assert r.this_month == 5 * TODAY.day and r.this_year == 5 * TODAY.timetuple().tm_yday
    # Projections run to the warranty end and End of Service Life of the last battery group
    g = res.groups[0]
    assert r.warranty_end == g.warranty_end and r.eosl == g.eosl
    assert r.at_eosl == pytest.approx(1825 + 5 * (g.eosl - TODAY).days)
    assert r.roi_at_eosl == pytest.approx((r.at_eosl - 20000) / 20000 * 100, abs=0.05)
    assert r.per_year == pytest.approx(5 * 365.25)



def test_roi_projections_per_group():
    """Each group's projections run to its own warranty end and EoSL; the setup's to the last group's."""
    first_install, added_install = TODAY - timedelta(days=700), TODAY - timedelta(days=100)
    days = {TODAY - timedelta(days=i): 4.0 for i in range(100)}
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 4, first_install, cost=20000),
                ledger.GroupInput(BAT8, 2, added_install, cost=8000)],
        today=TODAY, charged_kwh=5000, roi=_roi_input(days)))
    r = res.roi
    g1, g2 = res.groups
    assert r.eosl == g2.eosl and r.warranty_end == g2.warranty_end  # the last group's
    assert [g["end_of_service_life"] for g in r.groups] == [g1.eosl.isoformat(), g2.eosl.isoformat()]
    assert r.groups[0]["at_eosl"] == pytest.approx(r.savings + 4 * (g1.eosl - TODAY).days)
    assert r.groups[1]["at_eosl"] == r.at_eosl
    assert r.groups[0]["roi_at_eosl"] < r.roi_at_eosl


def test_roi_whole_installation_and_typed_savings():
    """Other system costs join the investment; savings before the figures join the savings."""
    install = TODAY - timedelta(days=9)
    days = {install + timedelta(days=i): 10.0 for i in range(10)}
    res = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 2, install, cost=8000)], today=TODAY, charged_kwh=100,
        roi=_roi_input(days, before=500.0, other=7000.0)))
    r = res.roi
    assert r.investment == 15000 and r.savings == 600 and not r.confident
    # Under 30 days counted: the rate is savings so far (typed included) over the days since the start
    assert r.daily_rate == 60 and r.days_to_go == 240


def test_roi_already_paid_back():
    install = TODAY - timedelta(days=99)
    days = {install + timedelta(days=i): 100.0 for i in range(100)}
    r = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 1, install, cost=5000)], today=TODAY, charged_kwh=100,
        roi=_roi_input(days))).roi
    assert r.net_position == 5000 and r.roi_pct == 100 and r.days_to_go == 0
    assert r.break_even == install + timedelta(days=49)  # the 50th $100 day reached $5,000


def test_roi_without_costs():
    """No battery cost or other costs: savings still count; no ROI, no break-even."""
    install = TODAY - timedelta(days=40)
    r = ledger.compute(ledger.LedgerInput(
        groups=[ledger.GroupInput(BAT8, 1, install)], today=TODAY, charged_kwh=100,
        roi=_roi_input({TODAY: 3.0}))).roi
    assert r.savings == 3 and r.investment is None and r.roi_pct is None and r.break_even is None


def test_break_even_too_far_out_has_no_date():
    """A few cents saved just after midnight, against a large investment: no break-even date rather than one
    millions of days away (which overflowed the date)."""
    today = date(2026, 11, 21)
    start = today - timedelta(days=20)
    res = ledger.compute_roi(ledger.RoiInput(total=0.02, days={today: 0.02}, start=start), 20000.0, today, start,
                             None, None)
    assert res.break_even is None and res.days_to_go is None
