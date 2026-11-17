"""Warranty, degradation and cost calculations.

Pure Python with no Home Assistant imports, so it can be unit tested directly.

Model
-----
Warranties are "X% capacity after N years or after T kWh of throughput, whichever
comes first". For each battery group we work out how far through the warranty it is
by time and by throughput, take the larger, and interpolate capacity linearly from
100% down to the warranted end-of-life capacity. That gives the **warranty floor**:
the minimum capacity the manufacturer guarantees at this point, not a measurement of
actual state of health.

When several groups (e.g. BAT 8.0 + BAT 10.0 modules) share one plant-level energy
counter, the counter can't be split exactly. It is allocated by
usable capacity x days in service, which assumes broadly even use over time.

Where per-module discharge counters are available (e.g. Sigen Cloud data via
sigenergy2mqtt) and the warranty limit is per unit and counted on discharged energy,
each module is measured against its own limit and the most-used module sets the
group's throughput position. Groups measured this way don't take a share of the
plant counter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DAYS_PER_YEAR = 365.25
LOW_CONFIDENCE_DAYS = 30

STATUS_ON_TRACK = "on_track"
STATUS_AHEAD = "ahead_of_time"
STATUS_EXPIRED = "expired"
DRIVER_AGE = "age"
DRIVER_THROUGHPUT = "throughput"
HW_MATCH = "match"
HW_MISMATCH = "mismatch"

_STATUS_RANK = {STATUS_ON_TRACK: 0, STATUS_AHEAD: 1, STATUS_EXPIRED: 2}


# Codes in LedgerResult.notes (sensor attribute "notes"); explained in the README.
NOTE_SPLIT_ESTIMATE = "plant_energy_split_by_capacity_and_age"
NOTE_BASIS_UNSTATED_CHARGED = "basis_unstated_using_charged"
NOTE_BASIS_UNSTATED_DISCHARGED = "basis_unstated_using_discharged"
NOTE_NO_DISCHARGED_SENSOR = "discharged_sensor_missing_using_charged"
NOTE_NO_CHARGED_SENSOR = "charged_sensor_missing_using_discharged"
NOTE_MODULES_NOT_USED = "module_counters_not_used"


class SpecError(ValueError):
    """A spec can't be used for the configured system."""


def throughput_limit_kwh(spec: dict, units: int) -> float | None:
    """Warranted throughput for `units` of this product, or None if unlimited."""
    tp = spec["warranty"]["throughput"]
    scope = tp["scope"]
    if scope == "none":
        return None
    if scope == "per_unit":
        return float(tp["kwh"]) * units
    if scope == "per_system":
        return float(tp["kwh"])
    if scope == "table":
        for row in tp["table"]:
            if row["units"] == units:
                return float(row["kwh"])
        allowed = ", ".join(str(r["units"]) for r in tp["table"])
        raise SpecError(f"warranty table has no entry for {units} units (has: {allowed})")
    raise SpecError(f"unknown throughput scope '{scope}'")


def validate_units(spec: dict, units: int) -> None:
    cap = spec["capacity"]
    if units < cap.get("min_units", 1):
        raise SpecError(f"minimum is {cap.get('min_units', 1)} units")
    if "max_units" in cap and units > cap["max_units"]:
        raise SpecError(f"maximum is {cap['max_units']} units")
    throughput_limit_kwh(spec, units)


def validate_spec(spec: dict) -> list[str]:
    """Light checks for manually entered specs (Store specs are validated upstream)."""
    errors = []
    cap = spec.get("capacity", {})
    w = spec.get("warranty", {})
    if not cap.get("usable_kwh", 0) > 0:
        errors.append("usable capacity must be above 0")
    if cap.get("nominal_kwh") and cap["usable_kwh"] > cap["nominal_kwh"]:
        errors.append("usable capacity cannot exceed nominal capacity")
    if not 0 < w.get("years", 0) <= 30:
        errors.append("warranty years must be between 0 and 30")
    if not 0 <= w.get("eol_capacity_pct", -1) <= 100:
        errors.append("end-of-life capacity must be 0-100%")
    tp = w.get("throughput", {})
    if tp.get("scope") in ("per_unit", "per_system") and not tp.get("kwh", 0) > 0:
        errors.append("throughput limit must be above 0")
    if tp.get("scope") == "table" and not tp.get("table"):
        errors.append("throughput table needs at least one row")
    return errors


@dataclass
class GroupInput:
    spec: dict
    units: int
    install_date: date
    # Per-module lifetime discharged kWh keyed by module ID (serial); used only when complete.
    module_kwh: dict[str, float] | None = None


@dataclass
class LedgerInput:
    groups: list[GroupInput]
    today: date
    charged_kwh: float | None = None
    discharged_kwh: float | None = None
    cost: float | None = None
    reported_capacity_kwh: float | None = None
    reported_soh_pct: float | None = None
    module_soc: dict[str, float] = field(default_factory=dict)


@dataclass
class GroupResult:
    label: str
    spec_id: str
    units: int
    install_date: date
    days_in_service: int
    basis_used: str
    basis_note: str | None
    limit_kwh: float | None
    used_kwh: float
    throughput_fraction: float | None
    time_fraction: float
    life_fraction: float
    floor_pct: float
    initial_usable_kwh: float
    floor_usable_kwh: float
    projected_kwh: float | None
    driver: str
    status: str
    source: str = "plant"  # "plant" (shared counter) or "modules"
    modules: dict[str, float] = field(default_factory=dict)  # module ID -> fraction of its limit used
    module_kwh: dict[str, float] = field(default_factory=dict)

    def as_attributes(self) -> dict:
        return {
            "label": self.label,
            "spec_id": self.spec_id,
            "units": self.units,
            "install_date": self.install_date.isoformat(),
            "throughput_basis": self.basis_used,
            "throughput_limit_kwh": _r(self.limit_kwh, 0),
            "throughput_used_kwh": _r(self.used_kwh, 1),
            "throughput_used_pct": _r(_pct(self.throughput_fraction), 2),
            "time_elapsed_pct": _r(_pct(self.time_fraction), 2),
            "warranty_floor_pct": _r(self.floor_pct, 1),
            "warranty_floor_kwh": _r(self.floor_usable_kwh, 2),
            "driver": self.driver,
            "status": self.status,
            "energy_source": self.source,
        }


@dataclass
class LedgerResult:
    groups: list[GroupResult]
    limit_kwh: float | None
    used_kwh: float
    remaining_kwh: float | None
    used_pct: float | None
    projected_kwh: float | None
    avg_daily_kwh: float | None
    low_confidence: bool
    initial_usable_kwh: float
    floor_usable_kwh: float
    floor_pct: float
    time_elapsed_pct: float
    driver: str
    status: str
    cost_per_kwh_rated: float | None
    cost_per_kwh_projected: float | None
    cost_consumed: float | None
    remaining_value: float | None
    remaining_value_by_life: float | None
    expected_reported_kwh: float | None
    hardware: str | None
    notes: list[str] = field(default_factory=list)
    worst_module_pct: float | None = None
    worst_module_id: str | None = None
    module_details: list[dict] = field(default_factory=list)
    module_vs_plant_pct: float | None = None
    soc_spread: float | None = None
    module_soc: dict[str, float] = field(default_factory=dict)
    reported_soh_pct: float | None = None
    health_margin: float | None = None
    reported_capacity_kwh: float | None = None
    total_units: int = 0


def _pct(frac):
    return None if frac is None else frac * 100


def _r(value, nd):
    return None if value is None else round(value, nd)


def _label(spec: dict) -> str:
    return " ".join(x for x in (spec.get("brand"), spec.get("model"), spec.get("variant")) if x)


def _energy_for_basis(basis: str, charged, discharged) -> tuple[float, str, str | None]:
    """Pick the energy counter for a warranty basis.

    Where the warranty doesn't say, or the preferred counter isn't configured, use
    charged energy when available: it is always >= discharged, so it errs towards
    using the warranty up sooner rather than overstating what's left.
    """
    if basis == "discharged" and discharged is not None:
        return discharged, "discharged", None
    if basis == "charged" and charged is not None:
        return charged, "charged", None
    if charged is not None:
        note = NOTE_BASIS_UNSTATED_CHARGED if basis == "unspecified" else NOTE_NO_DISCHARGED_SENSOR
        return charged, "charged", note
    if discharged is not None:
        note = NOTE_BASIS_UNSTATED_DISCHARGED if basis == "unspecified" else NOTE_NO_CHARGED_SENSOR
        return discharged, "discharged", note
    raise SpecError("no energy sensor available")


def _module_mode(g: GroupInput) -> bool:
    """Per-module counters can be used for this group's warranty position."""
    tp = g.spec["warranty"]["throughput"]
    return bool(
        g.module_kwh
        and len(g.module_kwh) == g.units
        and tp["scope"] == "per_unit"
        and tp["basis"] == "discharged"
    )


def compute(inp: LedgerInput) -> LedgerResult:
    if not inp.groups:
        raise SpecError("no battery groups configured")

    days = [max((inp.today - g.install_date).days, 0) for g in inp.groups]
    caps = [g.spec["capacity"]["usable_kwh"] * g.units for g in inp.groups]
    module_mode = [_module_mode(g) for g in inp.groups]
    weights = [0.0 if m else c * max(d, 1) for c, d, m in zip(caps, days, module_mode)]
    total_weight = sum(weights) or 1.0
    shares = [w / total_weight for w in weights]
    module_discharged = sum(sum(g.module_kwh.values()) for g, m in zip(inp.groups, module_mode) if m)

    notes: list[str] = []
    if sum(1 for m in module_mode if not m) > 1:
        notes.append(NOTE_SPLIT_ESTIMATE)
    for g, m in zip(inp.groups, module_mode):
        if g.module_kwh and not m:
            notes.append(f"{NOTE_MODULES_NOT_USED}:{g.spec.get('id', 'custom')}:{len(g.module_kwh)}/{g.units}")

    results: list[GroupResult] = []
    for g, d, share, initial, by_module in zip(inp.groups, days, shares, caps, module_mode):
        spec = g.spec
        w = spec["warranty"]
        limit = throughput_limit_kwh(spec, g.units)
        modules: dict[str, float] = {}
        if by_module:
            per_unit = float(w["throughput"]["kwh"])
            modules = {mid: max(kwh, 0.0) / per_unit for mid, kwh in g.module_kwh.items()}
            used = sum(max(k, 0.0) for k in g.module_kwh.values())
            basis_used, tp_frac = "discharged", max(modules.values())
        else:
            system_kwh, basis_used, basis_note = _energy_for_basis(
                w["throughput"]["basis"], inp.charged_kwh, inp.discharged_kwh)
            if basis_note and basis_note not in notes:
                notes.append(basis_note)
            if basis_used == "discharged" and module_discharged:
                system_kwh -= module_discharged  # what's left after module-measured groups
            used = max(system_kwh, 0.0) * share
            tp_frac = (used / limit) if limit else None
        warranty_days = w["years"] * DAYS_PER_YEAR
        time_frac = d / warranty_days
        life = max(time_frac, tp_frac or 0.0)
        eol = w["eol_capacity_pct"]
        floor_pct = 100 - (100 - eol) * min(life, 1.0)
        projected = None
        if limit is not None and d > 0:
            projected = min(used / d * warranty_days, limit)
        if life >= 1:
            status = STATUS_EXPIRED
        elif tp_frac is not None and tp_frac > time_frac:
            status = STATUS_AHEAD
        else:
            status = STATUS_ON_TRACK
        driver = DRIVER_THROUGHPUT if (tp_frac or 0) > time_frac else DRIVER_AGE
        results.append(GroupResult(
            label=_label(spec), spec_id=spec.get("id", "custom"), units=g.units,
            install_date=g.install_date, days_in_service=d, basis_used=basis_used,
            basis_note=None, limit_kwh=limit, used_kwh=used,
            throughput_fraction=tp_frac, time_fraction=time_frac, life_fraction=life,
            floor_pct=floor_pct, initial_usable_kwh=initial,
            floor_usable_kwh=initial * floor_pct / 100, projected_kwh=projected,
            driver=driver, status=status, source="modules" if by_module else "plant",
            modules=modules, module_kwh=dict(g.module_kwh) if by_module else {}))

    limited = [r for r in results if r.limit_kwh is not None]
    limit_total = sum(r.limit_kwh for r in limited) if limited else None
    used_limited = sum(r.used_kwh for r in limited)
    used_total = sum(r.used_kwh for r in results)
    remaining = max(limit_total - used_limited, 0.0) if limit_total else None
    used_pct = used_limited / limit_total * 100 if limit_total else None

    max_days = max(days)
    avg_daily = used_total / max_days if max_days > 0 else None
    projected_total = None
    if limited and all(r.projected_kwh is not None for r in limited):
        projected_total = sum(r.projected_kwh for r in limited)

    initial_total = sum(r.initial_usable_kwh for r in results)
    floor_total = sum(r.floor_usable_kwh for r in results)
    floor_pct = floor_total / initial_total * 100 if initial_total else 100.0
    time_pct = sum(r.time_fraction * r.initial_usable_kwh for r in results) / initial_total * 100

    worst = max(results, key=lambda r: r.life_fraction)
    status = max((r.status for r in results), key=_STATUS_RANK.get)

    cost = inp.cost if inp.cost and inp.cost > 0 else None
    cpk_rated = cost / limit_total if cost and limit_total else None
    cpk_proj = cost / projected_total if cost and projected_total else None
    consumed = min(cpk_rated * used_limited, cost) if cpk_rated else None
    remaining_value = cost - consumed if consumed is not None else None
    life_weighted = sum(min(r.life_fraction, 1.0) * r.initial_usable_kwh for r in results) / initial_total
    remaining_by_life = cost * (1 - life_weighted) if cost else None

    expected_reported = None
    hardware = None
    if all("reported_kwh" in g.spec["capacity"] or "nominal_kwh" in g.spec["capacity"] for g in inp.groups):
        expected_reported = sum(
            g.spec["capacity"].get("reported_kwh", g.spec["capacity"].get("nominal_kwh")) * g.units
            for g in inp.groups)
    if inp.reported_capacity_kwh is not None and expected_reported is not None:
        tolerance = max(0.2, expected_reported * 0.01)
        hardware = HW_MATCH if abs(inp.reported_capacity_kwh - expected_reported) <= tolerance else HW_MISMATCH

    module_details = [
        {"module": mid, "group": r.label, "discharged_kwh": round(r.module_kwh[mid], 1),
         "throughput_used_pct": round(frac * 100, 2)}
        for r in results for mid, frac in sorted(r.modules.items())
    ]
    worst_module_pct = worst_module_id = None
    if module_details:
        top = max(module_details, key=lambda m: m["throughput_used_pct"])
        worst_module_pct, worst_module_id = top["throughput_used_pct"], top["module"]
    module_vs_plant = None
    if all(module_mode) and inp.discharged_kwh:
        module_vs_plant = module_discharged / inp.discharged_kwh * 100

    soc_spread = (max(inp.module_soc.values()) - min(inp.module_soc.values())) if len(inp.module_soc) > 1 else None
    margin = inp.reported_soh_pct - floor_pct if inp.reported_soh_pct is not None else None

    return LedgerResult(
        groups=results, limit_kwh=limit_total, used_kwh=used_limited if limited else used_total,
        remaining_kwh=remaining, used_pct=used_pct, projected_kwh=projected_total,
        avg_daily_kwh=avg_daily, low_confidence=max_days < LOW_CONFIDENCE_DAYS,
        initial_usable_kwh=initial_total, floor_usable_kwh=floor_total, floor_pct=floor_pct,
        time_elapsed_pct=time_pct, driver=worst.driver, status=status,
        cost_per_kwh_rated=cpk_rated, cost_per_kwh_projected=cpk_proj, cost_consumed=consumed,
        remaining_value=remaining_value, remaining_value_by_life=remaining_by_life,
        expected_reported_kwh=expected_reported, hardware=hardware, notes=notes,
        worst_module_pct=worst_module_pct, worst_module_id=worst_module_id,
        module_details=module_details, module_vs_plant_pct=module_vs_plant,
        soc_spread=soc_spread, module_soc=dict(inp.module_soc),
        reported_soh_pct=inp.reported_soh_pct, health_margin=margin,
        reported_capacity_kwh=inp.reported_capacity_kwh, total_units=sum(g.units for g in inp.groups))
