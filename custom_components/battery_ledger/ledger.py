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
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # ledger.py stays loadable on its own (tests/test_ledger.py)
    from .capacity import Measured

DAYS_PER_YEAR = 365.25
LOW_CONFIDENCE_DAYS = 30

STATUS_ON_TRACK = "on_track"
STATUS_AHEAD = "ahead_of_time"
STATUS_EXPIRED = "expired"
DRIVER_AGE = "age"
# Cost per kWh (Export): each basis, and what its "basis" attribute says. The warranty basis is the higher of
# age and usage (whichever limit ends the warranty first); usage is used for the first 30 days.
BASIS_AGE = "age"  # cost ÷ throughput projected by the warranty end date, at the average rate so far
BASIS_USAGE = "usage"  # cost ÷ warranted throughput
BASIS_ESL = "esl"  # cost ÷ throughput projected over the Estimated Service Life
BASIS_SOH_TREND = "soh_trend"  # cost ÷ throughput projected until the SoH trend reaches the warranty capacity
# The export cost setting (select entity / Configure)
EXPORT_WARRANTY = "warranty"  # whichever warranty limit ends first (the higher of age and usage)
EXPORT_AGE = "age"
EXPORT_USAGE = "usage"
EXPORT_ESL = "esl"
EXPORT_CHEAPEST = "cheapest"
EXPORT_SETTINGS = (EXPORT_WARRANTY, EXPORT_AGE, EXPORT_USAGE, EXPORT_ESL, EXPORT_CHEAPEST)
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
# Energy counters read 0 on a battery in service for a while: almost always a source that isn't
# reporting (e.g. an integration publishing 0), not a battery that hasn't been used.
NOTE_ENERGY_ZERO = "energy_counters_zero"
ENERGY_ZERO_DAYS = 30


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
    # What this group cost (batteries added later have their own cost and warranty clock).
    cost: float | None = None


@dataclass
class LedgerInput:
    groups: list[GroupInput]
    today: date
    charged_kwh: float | None = None
    discharged_kwh: float | None = None
    reported_capacity_kwh: float | None = None
    reported_soh_pct: float | None = None
    module_soc: dict[str, float] = field(default_factory=dict)
    # Estimated Service Life in years, counted from each group's warranty start; None = default_esl_years
    esl_years: float | None = None
    export_setting: str = EXPORT_WARRANTY
    # Years the SoH trend suggests until the warranty capacity is reached (None: not enough history)
    soh_trend_years: float | None = None
    # Usable capacity measured from state-of-charge runs (capacity.py); None without a SoC sensor or towers
    measured: Measured | None = None
    # Each battery tower's measurement and the battery group (index) it's in, when towers are measured
    tower_measured: list[tuple[int, Measured]] = field(default_factory=list)


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
    warranty_years: float = 0.0
    eol_pct: float = 0.0
    warranty_end: date | None = None
    # When the throughput limit is reached at the average rate so far (may be after warranty_end).
    usage_end: date | None = None
    cost: float | None = None
    cost_consumed: float | None = None
    # This group's own financials (as the setup's, for this group alone); None without a cost
    remaining_value: float | None = None
    cost_per_kwh_rated: float | None = None
    cost_per_kwh_projected: float | None = None
    cost_per_kwh_export: float | None = None
    export_basis: str | None = None
    # Throughput at the average rate so far until the warranty end date, not capped at the limit.
    projected_uncapped_kwh: float | None = None
    # End of Service Life: warranty start + Estimated Service Life; throughput projected until then
    eosl: date | None = None
    projected_esl_kwh: float | None = None
    projected_soh_kwh: float | None = None
    # Measured from this group's towers: their usable capacity added up ÷ the group's usable capacity when new
    measured_usable_kwh: float | None = None
    measured_soh_pct: float | None = None

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
            "warranty_years": self.warranty_years,
            "warranty_end_date": self.warranty_end.isoformat() if self.warranty_end else None,
            "throughput_end_date": self.usage_end.isoformat() if self.usage_end else None,
            "end_of_warranty_capacity_pct": self.eol_pct,
            "driver": self.driver,
            "status": self.status,
            "energy_source": self.source,
            "cost": _r(self.cost, 2),
            "cost_consumed": _r(self.cost_consumed, 2),
            "remaining_value": _r(self.remaining_value, 2),
            "cost_per_kwh_rated": _r(self.cost_per_kwh_rated, 6),
            "cost_per_kwh_projected": _r(self.cost_per_kwh_projected, 6),
            "cost_per_kwh_export": _r(self.cost_per_kwh_export, 6),
            "export_basis": self.export_basis,
            "end_of_service_life": self.eosl.isoformat() if self.eosl else None,
            "projected_throughput_kwh": _r(self.projected_kwh, 0),
            "projected_esl_throughput_kwh": _r(self.projected_esl_kwh, 0),
            "measured_usable_kwh": _r(self.measured_usable_kwh, 2),
            "measured_soh_pct": _r(self.measured_soh_pct, 1),
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
    cycles_per_day: float | None = None
    # For a home energy manager's battery cost / minimum sell price (see BASIS_* / EXPORT_*)
    cost_per_kwh_export: float | None = None
    export_basis: str | None = None
    export_costs: dict[str, float | None] = field(default_factory=dict)  # basis -> cost per kWh
    esl_years: float | None = None
    eosl: date | None = None  # earliest End of Service Life among the groups
    # Estimated usage at EoSL: each group's throughput at the average rate so far, to its End of Service Life
    projected_esl_kwh: float | None = None
    soh_trend_years: float | None = None
    measured: Measured | None = None
    measured_soh_pct: float | None = None  # measured usable ÷ usable when new
    tower_details: list[dict] = field(default_factory=list)  # each tower's measurement, for the attributes


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


ESL_DEFAULT_YEARS = 15  # Estimated Service Life until the user sets one


def default_esl_years(specs: list[dict]) -> float:
    """Estimated Service Life until the user sets one: 15 years, or the longest warranty if that's longer."""
    return float(max([ESL_DEFAULT_YEARS, *(s["warranty"]["years"] for s in specs)]))


def _add_years(start: date, years: float) -> date:
    """Calendar years (15 years from 2020-03-01 is 2035-03-01), then any fraction in days."""
    whole = int(years)
    try:
        end = start.replace(year=start.year + whole)
    except ValueError:  # 29 February
        end = start.replace(year=start.year + whole, day=28)
    return end + timedelta(days=round((years - whole) * DAYS_PER_YEAR))


def _financials(costed: list[GroupResult], days: int, export_setting: str | None) -> dict:
    """Value used, remaining value and cost per kWh (by usage, by age, export) for these battery groups (the
    setup's costed groups, or one group). Each group's cost_consumed must be set."""
    cost = sum(r.cost for r in costed) if costed else None
    consumed = sum(r.cost_consumed for r in costed) if costed else None
    remaining_value = cost - consumed if consumed is not None else None
    costed_limits = [r.limit_kwh for r in costed]
    cpk_rated = cost / sum(costed_limits) if cost and costed_limits and None not in costed_limits else None
    costed_proj = [r.projected_kwh for r in costed]
    cpk_proj = (cost / sum(costed_proj) if cost and costed_proj and None not in costed_proj and sum(costed_proj) > 0
                else None)

    # Cost per kWh (Export). Per basis: age (cost ÷ throughput by the warranty end date, not capped), usage
    # (rated), ESL and SoH trend (cost ÷ throughput over those lives). The warranty basis is the higher of age
    # and usage: whichever limit ends the warranty first. Usage for the first 30 days, as an early projection
    # can be far too high for a minimum sell price.
    def per_kwh(kwhs: list[float | None]) -> float | None:
        return cost / sum(kwhs) if cost and kwhs and None not in kwhs and sum(kwhs) > 0 else None

    costs: dict[str, float | None] = {
        BASIS_AGE: per_kwh([r.projected_uncapped_kwh for r in costed]),
        BASIS_USAGE: cpk_rated,
        BASIS_ESL: per_kwh([r.projected_esl_kwh for r in costed]),
        BASIS_SOH_TREND: per_kwh([r.projected_soh_kwh for r in costed]),
    }
    cpk_export = export_basis = None
    if cost and days < LOW_CONFIDENCE_DAYS:
        if costs[BASIS_USAGE] is not None:
            export_basis = BASIS_USAGE
    elif cost:
        warranty = [b for b in (BASIS_AGE, BASIS_USAGE) if costs[b] is not None]
        warranty_basis = max(warranty, key=lambda b: costs[b]) if warranty else None
        chosen = {EXPORT_AGE: BASIS_AGE, EXPORT_USAGE: BASIS_USAGE, EXPORT_ESL: BASIS_ESL}.get(export_setting)
        if chosen and costs[chosen] is not None:
            export_basis = chosen  # without that figure (e.g. no throughput limit), the warranty basis
        elif export_setting == EXPORT_CHEAPEST:
            choices = [b for b in (warranty_basis, BASIS_ESL, BASIS_SOH_TREND) if b and costs[b] is not None]
            export_basis = min(choices, key=lambda b: costs[b]) if choices else None
        else:
            export_basis = warranty_basis
    if export_basis:
        cpk_export = costs[export_basis]
    return {"cost": cost, "consumed": consumed, "remaining_value": remaining_value, "cpk_rated": cpk_rated,
            "cpk_proj": cpk_proj, "cpk_export": cpk_export, "export_basis": export_basis, "costs": costs}


def compute(inp: LedgerInput) -> LedgerResult:
    if not inp.groups:
        raise SpecError("no battery groups configured")
    esl_years = inp.esl_years or default_esl_years([g.spec for g in inp.groups])

    days = [max((inp.today - g.install_date).days, 0) for g in inp.groups]
    caps = [g.spec["capacity"]["usable_kwh"] * g.units for g in inp.groups]
    module_mode = [_module_mode(g) for g in inp.groups]
    weights = [0.0 if m else c * max(d, 1) for c, d, m in zip(caps, days, module_mode, strict=True)]
    total_weight = sum(weights) or 1.0
    shares = [w / total_weight for w in weights]
    module_discharged = sum(sum(g.module_kwh.values()) for g, m in zip(inp.groups, module_mode, strict=True) if m)

    notes: list[str] = []
    if sum(1 for m in module_mode if not m) > 1:
        notes.append(NOTE_SPLIT_ESTIMATE)
    for g, m in zip(inp.groups, module_mode, strict=True):
        if g.module_kwh and not m:
            notes.append(f"{NOTE_MODULES_NOT_USED}:{g.spec.get('id', 'custom')}:{len(g.module_kwh)}/{g.units}")

    results: list[GroupResult] = []
    for g, d, share, initial, by_module in zip(inp.groups, days, shares, caps, module_mode, strict=True):
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
        esl_days = esl_years * DAYS_PER_YEAR
        time_frac = d / warranty_days
        life = max(time_frac, tp_frac or 0.0)
        eol = w["eol_capacity_pct"]
        floor_pct = 100 - (100 - eol) * min(life, 1.0)
        projected = uncapped = None
        if d > 0:
            uncapped = used / d * warranty_days
            if limit is not None:
                projected = min(uncapped, limit)
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
            modules=modules, module_kwh=dict(g.module_kwh) if by_module else {},
            warranty_years=w["years"], eol_pct=eol, projected_uncapped_kwh=uncapped,
            eosl=_add_years(g.install_date, esl_years),
            projected_esl_kwh=used / d * esl_days if d > 0 else None,
            projected_soh_kwh=used / d * inp.soh_trend_years * DAYS_PER_YEAR
            if d > 0 and inp.soh_trend_years else None,
            warranty_end=g.install_date + timedelta(days=round(warranty_days)),
            usage_end=(g.install_date + timedelta(days=round(limit / (used / d))))
            if limit and d > 0 and used > 0 else None,
            cost=g.cost if g.cost and g.cost > 0 else None))

    limited = [r for r in results if r.limit_kwh is not None]
    limit_total = sum(r.limit_kwh for r in limited) if limited else None
    used_limited = sum(r.used_kwh for r in limited)
    used_total = sum(r.used_kwh for r in results)
    remaining = max(limit_total - used_limited, 0.0) if limit_total else None
    used_pct = used_limited / limit_total * 100 if limit_total else None

    max_days = max(days)
    if used_total == 0 and max_days >= ENERGY_ZERO_DAYS:
        notes.append(NOTE_ENERGY_ZERO)
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

    # Cost per battery group: each group's cost is used up at the rate of its warranty driver (its life
    # fraction: the larger of time elapsed and throughput used), capped at that group's whole cost.
    # Cost per kWh covers the groups that have a cost.
    costed = [r for r in results if r.cost is not None]
    for r in costed:
        r.cost_consumed = r.cost * min(r.life_fraction, 1.0)
    fin = _financials(costed, max_days, inp.export_setting)
    consumed, remaining_value, costs = fin["consumed"], fin["remaining_value"], fin["costs"]
    cpk_rated, cpk_proj = fin["cpk_rated"], fin["cpk_proj"]
    cpk_export, export_basis = fin["cpk_export"], fin["export_basis"]
    # Each group's own figures, the same way, for the card's group switcher
    for r in costed:
        own = _financials([r], r.days_in_service, inp.export_setting)
        r.remaining_value, r.cost_per_kwh_rated = own["remaining_value"], own["cpk_rated"]
        r.cost_per_kwh_projected = own["cpk_proj"]
        r.cost_per_kwh_export, r.export_basis = own["cpk_export"], own["export_basis"]

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

    # Full equivalent cycles per day, as the original YAML package's battery_cycles_per_day:
    # energy / days in service / capacity. Capacity: what the inverter reports, else the spec's figure.
    cycle_capacity = inp.reported_capacity_kwh or expected_reported or initial_total
    cycles = used_total / max_days / cycle_capacity if max_days > 0 and cycle_capacity else None

    # Battery towers: each group's measured capacity is its towers' added up; a tower's SoH is against its share of
    # the group's usable capacity when new (the group's towers taken as equal in size)
    tower_details = []
    per_group: dict[int, list] = {}
    for grp, m in inp.tower_measured:
        per_group.setdefault(min(max(grp, 0), len(results) - 1), []).append(m)
    for grp, ms in per_group.items():
        r = results[grp]
        if all(m.usable_kwh is not None for m in ms):
            r.measured_usable_kwh = sum(m.usable_kwh for m in ms)
            r.measured_soh_pct = r.measured_usable_kwh / r.initial_usable_kwh * 100 if r.initial_usable_kwh else None
    for n, (grp, m) in enumerate(inp.tower_measured, start=1):
        grp = min(max(grp, 0), len(results) - 1)
        share = results[grp].initial_usable_kwh / len(per_group[grp]) if results[grp].initial_usable_kwh else None
        tower_details.append({
            "tower": n, "group": grp + 1, "status": m.status, "usable_kwh": m.usable_kwh,
            "soh_pct": _r(m.usable_kwh / share * 100, 1) if m.usable_kwh is not None and share else None,
            "round_trip_efficiency_pct": m.efficiency_pct,
            "charge_runs": m.charge_runs, "discharge_runs": m.discharge_runs})

    return LedgerResult(
        groups=results, limit_kwh=limit_total, used_kwh=used_limited if limited else used_total,
        remaining_kwh=remaining, used_pct=used_pct, projected_kwh=projected_total,
        avg_daily_kwh=avg_daily, low_confidence=max_days < LOW_CONFIDENCE_DAYS,
        initial_usable_kwh=initial_total, floor_usable_kwh=floor_total, floor_pct=floor_pct,
        time_elapsed_pct=time_pct, driver=worst.driver, status=status,
        cost_per_kwh_rated=cpk_rated, cost_per_kwh_projected=cpk_proj, cost_consumed=consumed,
        remaining_value=remaining_value,
        expected_reported_kwh=expected_reported, hardware=hardware, notes=notes,
        worst_module_pct=worst_module_pct, worst_module_id=worst_module_id,
        module_details=module_details, module_vs_plant_pct=module_vs_plant,
        soc_spread=soc_spread, module_soc=dict(inp.module_soc),
        reported_soh_pct=inp.reported_soh_pct, health_margin=margin,
        reported_capacity_kwh=inp.reported_capacity_kwh, total_units=sum(g.units for g in inp.groups),
        cycles_per_day=cycles, cost_per_kwh_export=cpk_export, export_basis=export_basis,
        export_costs=costs,
        esl_years=esl_years, soh_trend_years=inp.soh_trend_years,
        measured=inp.measured, tower_details=tower_details,
        measured_soh_pct=inp.measured.usable_kwh / initial_total * 100
        if inp.measured and inp.measured.usable_kwh is not None and initial_total else None,
        projected_esl_kwh=sum(esl_kwh) if (esl_kwh := [r.projected_esl_kwh for r in results]) and None not in esl_kwh
        else None, eosl=min(r.eosl for r in results) if results else None)
