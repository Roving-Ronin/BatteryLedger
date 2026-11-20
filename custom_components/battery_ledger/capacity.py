"""Measured usable capacity: what the battery really holds, from energy in and out against its state of charge.

Pure Python, no Home Assistant imports. Method (after Energy Pilot, MIT licensed): each run of charging or
discharging in which the state of charge moves at least MIN_RUN_POINTS is written down as kWh per percentage
point. Charging needs capacity/100 ÷ charge efficiency per point; discharging gives capacity/100 × discharge
efficiency. So the geometric mean of the two is the usable capacity with the losses cancelled out, and their
ratio the round-trip efficiency. Medians of the last KEEP runs each way smooth out the BMS's state-of-charge
drift and calibration jumps.

Energy comes from the lifetime charged and discharged counters, so no power sensor is needed: a charging run
counts what went in minus anything that came out meanwhile, and the other way round.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median
from typing import Any

MIN_RUN_POINTS = 10  # a run must move the state of charge this many points
REVERSAL_POINTS = 2  # a move this far back from the run's furthest point ends it
MIN_RUNS = 3  # each way, before a capacity is given
KEEP = 20  # runs kept each way
PER_POINT_RANGE = (0.01, 10.0)  # kWh per point: 1 to 1,000 kWh batteries

STATUS_OK = "ok"
STATUS_ONE_WAY = "one_direction"  # only one energy counter: one way, losses not cancelled
STATUS_INSUFFICIENT = "insufficient"


@dataclass
class Measured:
    usable_kwh: float | None
    efficiency_pct: float | None  # round trip
    charge_runs: int | None  # None: no charged-energy counter, so charging isn't measured
    discharge_runs: int | None
    status: str


class CapacityLearner:
    """Keeps its state in a JSON-able dict (`state`), saved by the caller between restarts."""

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state: dict[str, Any] = state if isinstance(state, dict) else {}
        self.state.setdefault("in_pp", [])
        self.state.setdefault("out_pp", [])
        self.state.setdefault("run", None)

    def observe(self, soc: float | None, charged_kwh: float | None, discharged_kwh: float | None) -> bool:
        """One reading. Returns True when a run was recorded (the caller then saves the state)."""
        if soc is None or (charged_kwh is None and discharged_kwh is None):
            return False
        # Which counters there are: with both, a capacity needs runs both ways
        self.state["counters"] = sorted({*self.state.get("counters", []),
                                         *(["ch"] if charged_kwh is not None else []),
                                         *(["dis"] if discharged_kwh is not None else [])})
        point = {"soc": float(soc), "ch": charged_kwh, "dis": discharged_kwh}
        run = self.state.get("run")
        if run is None:
            self.state["run"] = {"way": None, "start": point, "peak": point}
            return False
        peak = run["peak"]
        way = run["way"]
        if way is None:
            if abs(point["soc"] - peak["soc"]) >= 1:
                run["way"] = "in" if point["soc"] > peak["soc"] else "out"
                run["peak"] = point
            else:
                run["start"] = run["peak"] = point  # idle: the run starts from here
            return False
        further = point["soc"] > peak["soc"] if way == "in" else point["soc"] < peak["soc"]
        back = peak["soc"] - point["soc"] if way == "in" else point["soc"] - peak["soc"]
        if further or (point["soc"] == peak["soc"]):
            run["peak"] = point if further else {**point, "soc": peak["soc"]}
            return False
        if back < REVERSAL_POINTS:
            return False
        # The run ended at its furthest point: record it, and start the next one from there
        recorded = self._record(way, run["start"], peak)
        self.state["run"] = {"way": "out" if way == "in" else "in", "start": peak, "peak": point}
        return recorded

    def _record(self, way: str, start: dict, end: dict) -> bool:
        moved = abs(end["soc"] - start["soc"])
        if moved < MIN_RUN_POINTS:
            return False

        def delta(key: str) -> float:
            a, b = start.get(key), end.get(key)
            return b - a if a is not None and b is not None else 0.0

        if start.get("ch") is None and start.get("dis") is None:
            return False
        net = delta("ch") - delta("dis") if way == "in" else delta("dis") - delta("ch")
        # The counter for this direction must be known, or the run can't be measured
        if (way == "in" and start.get("ch") is None) or (way == "out" and start.get("dis") is None):
            return False
        per = net / moved
        if not PER_POINT_RANGE[0] <= per <= PER_POINT_RANGE[1]:
            return False  # a counter reset, a jump in the state of charge, or the wrong sensor
        key = f"{way}_pp"
        self.state[key] = [*self.state.get(key, []), round(per, 5)][-KEEP:]
        return True

    def measured(self) -> Measured:
        ins, outs = self.state.get("in_pp") or [], self.state.get("out_pp") or []
        counters = self.state.get("counters") or []
        n_in = len(ins) if "ch" in counters else None
        n_out = len(outs) if "dis" in counters else None
        if n_in is not None and n_out is not None:
            if n_in < MIN_RUNS or n_out < MIN_RUNS:
                return Measured(None, None, n_in, n_out, STATUS_INSUFFICIENT)
            pin, pout = median(ins), median(outs)
            return Measured(round(sqrt(pin * pout) * 100, 2), round(min(100.0, pout / pin * 100), 1),
                            n_in, n_out, STATUS_OK)
        one = outs if n_out is not None else ins if n_in is not None else []
        if len(one) >= MIN_RUNS:
            return Measured(round(median(one) * 100, 2), None, n_in, n_out, STATUS_ONE_WAY)
        return Measured(None, None, n_in, n_out, STATUS_INSUFFICIENT)


def combine(towers: list[Measured]) -> Measured:
    """The whole battery from its towers: capacities added up once every tower has one; efficiency weighted by
    capacity; the run counts of the tower furthest behind, so "how far it's got" is the slowest tower's."""
    if not towers:
        return Measured(None, None, None, None, STATUS_INSUFFICIENT)
    known = [t for t in towers if t.usable_kwh is not None]
    status = (STATUS_INSUFFICIENT if len(known) < len(towers)
              else STATUS_ONE_WAY if any(t.status == STATUS_ONE_WAY for t in towers) else STATUS_OK)
    usable = round(sum(t.usable_kwh for t in known), 2) if status != STATUS_INSUFFICIENT else None
    with_eff = [t for t in known if t.efficiency_pct is not None]
    eff = (round(sum(t.efficiency_pct * t.usable_kwh for t in with_eff) / sum(t.usable_kwh for t in with_eff), 1)
           if usable is not None and with_eff and len(with_eff) == len(towers) else None)

    def slowest(runs: list[int | None]) -> int | None:
        counted = [r for r in runs if r is not None]
        return min(counted) if counted else None

    return Measured(usable, eff, slowest([t.charge_runs for t in towers]),
                    slowest([t.discharge_runs for t in towers]), status)
