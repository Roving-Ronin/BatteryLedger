"""Measured usable capacity (capacity.py): runs of state of charge against energy in and out."""

import pytest

from custom_components.battery_ledger.capacity import STATUS_INSUFFICIENT, STATUS_OK, STATUS_ONE_WAY, CapacityLearner


def _cycle(learner, cap=40.0, eff=0.95, lo=20, hi=90, start=(0.0, 0.0), days=4):
    """Charge lo→hi and discharge hi→lo `days` times, 1 point per step; charge takes capacity/100/√eff per point,
    discharge gives capacity/100 × √eff."""
    ch, dis = start
    soc = lo
    learner.observe(soc, ch, dis)
    step_in, step_out = cap / 100 / eff ** 0.5, cap / 100 * eff ** 0.5
    for _ in range(days):
        while soc < hi:
            soc += 1
            ch += step_in
            learner.observe(soc, ch, dis)
        while soc > lo:
            soc -= 1
            dis += step_out
            learner.observe(soc, ch, dis)
    for _ in range(3):  # turn back up, which ends the last discharge run
        soc += 1
        ch += step_in
        learner.observe(soc, ch, dis)
    return ch, dis


def test_capacity_and_efficiency_from_runs():
    learner = CapacityLearner()
    assert learner.measured().status == STATUS_INSUFFICIENT
    _cycle(learner)
    m = learner.measured()
    assert m.status == STATUS_OK and m.charge_runs >= 3 and m.discharge_runs >= 3
    assert m.usable_kwh == pytest.approx(40.0, rel=0.02)
    assert m.efficiency_pct == pytest.approx(95.0, abs=0.5)


def test_both_counters_wait_for_runs_both_ways():
    """With both counters a one-way figure isn't given: losses would be counted in."""
    learner = CapacityLearner()
    soc, ch, dis = 90, 0.0, 0.0
    learner.observe(soc, ch, dis)
    for _ in range(4):  # discharges count; charges don't (the charged counter doesn't move, so they're rejected)
        while soc > 20:
            soc -= 1
            dis += 0.38
            learner.observe(soc, ch, dis)
        while soc < 90:
            soc += 1
            learner.observe(soc, ch, dis)
    for _ in range(3):
        soc -= 1
        learner.observe(soc, ch, dis)
    m = learner.measured()
    assert m.status == STATUS_INSUFFICIENT and m.usable_kwh is None
    assert m.discharge_runs >= 3 and m.charge_runs == 0


def test_small_moves_and_noise_ignored():
    learner = CapacityLearner()
    ch = dis = 0.0
    soc = 50
    for i in range(200):  # wobbles of a few points never make a run
        soc += 1 if i % 6 < 3 else -1
        ch += 0.4
        dis += 0.4
        learner.observe(soc, ch, dis)
    assert learner.state["in_pp"] == [] and learner.state["out_pp"] == []


def test_counter_reset_rejected():
    learner = CapacityLearner()
    learner.observe(20, 1000.0, 900.0)
    for soc in range(21, 40):
        learner.observe(soc, 1000.0 + (soc - 20) * 0.4, 900.0)
    for soc in range(40, 60):  # counters reset mid-run: the run comes out negative and isn't recorded
        learner.observe(soc, (soc - 40) * 0.4, 0.0)
    learner.observe(57, 7.6, 0.0)
    assert learner.state["in_pp"] == []


def test_one_counter_gives_one_way_capacity():
    learner = CapacityLearner()
    soc, dis = 90, 0.0
    learner.observe(soc, None, dis)
    for _ in range(4):
        while soc > 20:
            soc -= 1
            dis += 0.4
            learner.observe(soc, None, dis)
        while soc < 90:
            soc += 1
            learner.observe(soc, None, dis)
    m = learner.measured()
    assert m.status == STATUS_ONE_WAY and m.usable_kwh == pytest.approx(40.0, rel=0.01) and m.efficiency_pct is None
    assert m.charge_runs is None  # no charged counter: charging isn't measured


def test_state_survives_a_restart():
    learner = CapacityLearner()
    _cycle(learner)
    again = CapacityLearner(dict(learner.state))
    assert again.measured() == learner.measured()


def test_combine_towers():
    from custom_components.battery_ledger.capacity import Measured, combine

    a = Measured(13.5, 92.0, 5, 4, STATUS_OK)
    b = Measured(6.5, 88.0, 3, 6, STATUS_OK)
    m = combine([a, b])
    assert m.status == STATUS_OK and m.usable_kwh == 20.0
    assert m.efficiency_pct == pytest.approx((92 * 13.5 + 88 * 6.5) / 20, abs=0.1)
    assert (m.charge_runs, m.discharge_runs) == (3, 4)  # the tower furthest behind
    learning = combine([a, Measured(None, None, 1, 2, STATUS_INSUFFICIENT)])
    assert learning.status == STATUS_INSUFFICIENT and learning.usable_kwh is None and learning.charge_runs == 1
    assert combine([a, Measured(6.0, None, None, 3, STATUS_ONE_WAY)]).status == STATUS_ONE_WAY
