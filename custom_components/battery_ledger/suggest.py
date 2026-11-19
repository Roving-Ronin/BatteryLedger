"""Suggest the battery model and unit count from what an integration reports.

Pure Python (no Home Assistant imports). The config flow gathers the readings; this works out
which Store specs fit, for the user to confirm. Nothing is ever chosen without the user.

Signals, strongest first, for each inverter / tower / system:
- per-module rated capacity (one reading per module), or
- rated capacity and a module count: capacity ÷ count = capacity per module, or
- rated capacity alone: a whole number of modules of one spec within tolerance.
Inverter model text narrows the model line (e.g. "SigenStor EC 30.0 TP AU" → SigenStor, not Neo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ledger import SpecError, validate_units

# Capacity per module: readings are rounded (e.g. 48.36 ÷ 6), so allow a little either way.
MODULE_TOLERANCE = 0.03
# Total capacity: as the hardware check (1%, at least 0.2 kWh).
TOTAL_TOLERANCE = 0.01
TOTAL_TOLERANCE_MIN_KWH = 0.2


@dataclass
class Reading:
    """What one inverter / tower / system reports about its batteries."""

    rated_kwh: float | None = None
    count: int | None = None
    model_text: str | None = None
    module_kwh: list[float] = field(default_factory=list)
    # Data-only label for the tower / inverter, e.g. "1 · SUN2000-5KTL-L1 · 2" (inverter · model · tower)
    place: str = ""


@dataclass
class Suggestion:
    """Either decided groups (spec, units), or candidate specs to choose from (with units if known)."""

    groups: list[tuple[dict, int]] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    units: dict[str, int] = field(default_factory=dict)

    @property
    def decided(self) -> bool:
        return bool(self.groups)


def module_kwh(spec: dict) -> float | None:
    """The capacity an integration reports for one unit of this spec."""
    cap = spec["capacity"]
    return cap.get("reported_kwh") or cap.get("nominal_kwh") or cap.get("usable_kwh")


def _valid_units(spec: dict, units: int) -> bool:
    try:
        validate_units(spec, units)
    except SpecError:
        return False
    return True


def _figures(spec: dict) -> tuple:
    """Everything the maths uses: specs equal here differ only in name (e.g. a rebadged battery)."""
    cap = spec["capacity"]
    return (cap.get("unit"), module_kwh(spec), cap.get("usable_kwh"), cap.get("min_units"), cap.get("max_units"),
            repr(sorted({k: v for k, v in spec["warranty"].items() if k != "notes"}.items())))


def _dedupe(specs: list[dict]) -> list[dict]:
    """Drop rebadged twins: a spec of another brand with identical figures to one already kept.

    The maths is the same either way, so the first (Store order) is shown as detected. Two models
    of the same brand stay separate (e.g. SigenStor BAT 6.0 and Neo BAT 6.0): their names differ.
    """
    kept: dict[tuple, set[str]] = {}
    out = []
    for s in specs:
        brands = kept.setdefault(_figures(s), set())
        if brands and s["brand"] not in brands:
            continue
        brands.add(s["brand"])
        out.append(s)
    return out


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def narrow_by_model(specs: list[dict], model_text: str | None) -> list[dict]:
    """Keep the specs whose model line (series) is named in the inverter model, longest line first.

    "SigenStor EC 30.0 TP AU" names SigenStor but not SigenStor Neo; text naming no line keeps all.
    """
    if not model_text:
        return specs
    words = _words(model_text)
    named = [s for s in specs if s.get("series") and _words(s["series"]) <= words]
    if not named:
        return specs
    longest = max(len(_words(s["series"])) for s in named)
    return [s for s in named if len(_words(s["series"])) == longest]


def _fits_module(spec: dict, kwh: float) -> bool:
    ref = module_kwh(spec)
    return spec["capacity"]["unit"] == "module" and bool(ref) and abs(kwh - ref) <= ref * MODULE_TOLERANCE


def fits_any_module(spec: dict, module_kwh: list[float]) -> bool:
    """The spec matches at least one module's reported capacity (or there are no module readings)."""
    return not module_kwh or any(_fits_module(spec, k) for k in module_kwh)


def reading_options(specs: list[dict], reading: Reading) -> list[tuple[dict, int]]:
    """(spec, units) that fit one reading. When capacity ÷ module count fits nothing (e.g. an inverter with more
    towers than the integration has serial number sensors for), fall back to the rated capacity alone."""
    found = _options(specs, reading)
    if not found and reading.count and reading.rated_kwh:
        found = _options(specs, Reading(rated_kwh=reading.rated_kwh, model_text=reading.model_text))
    return found


def _options(specs: list[dict], reading: Reading) -> list[tuple[dict, int]]:
    """(spec, units) that fit one reading."""
    specs = narrow_by_model(specs, reading.model_text)
    if reading.module_kwh:
        # One spec has to fit every module (mixed modules on one inverter are left to the user).
        fits = [s for s in specs if all(_fits_module(s, k) for k in reading.module_kwh)]
        return [(s, len(reading.module_kwh)) for s in _dedupe(fits)]
    if reading.rated_kwh is None or reading.rated_kwh <= 0:
        return []
    if reading.count:
        per = reading.rated_kwh / reading.count
        return [(s, reading.count) for s in _dedupe([s for s in specs if _fits_module(s, per)])]
    out = []
    tolerance = max(TOTAL_TOLERANCE_MIN_KWH, reading.rated_kwh * TOTAL_TOLERANCE)
    for s in _dedupe(specs):
        ref = module_kwh(s)
        if not ref:
            continue
        units = round(reading.rated_kwh / ref)
        if units >= 1 and abs(units * ref - reading.rated_kwh) <= tolerance and _valid_units(s, units):
            out.append((s, units))
    return out


def suggest(specs: list[dict], readings: list[Reading]) -> Suggestion:
    """Specs (already narrowed to the system's brands, in Store order) that fit every reading."""
    per_reading = [reading_options(specs, r) for r in readings]
    per_reading = [o for o in per_reading if o]
    if not per_reading:
        return Suggestion()

    if all(len(o) == 1 for o in per_reading):
        # Decided: merge inverters with the same spec while the total is still a valid unit count
        # (a spec's unit limits are per inverter / stack); otherwise keep a group each.
        groups: list[list] = []
        for (spec, units), in per_reading:
            for g in groups:
                if g[0]["id"] == spec["id"] and _valid_units(spec, g[1] + units):
                    g[1] += units
                    break
            else:
                groups.append([spec, units])
        return Suggestion(groups=[(s, u) for s, u in groups])

    candidates: list[dict] = []
    units: dict[str, set[int]] = {}
    for options in per_reading:
        for spec, n in options:
            if spec["id"] not in units:
                candidates.append(spec)
            units.setdefault(spec["id"], set()).add(n)
    if len(per_reading) > 1:
        # Several inverters that don't settle on one model each: the user chooses, units aren't pre-filled.
        return Suggestion(candidates=candidates)
    return Suggestion(candidates=candidates, units={sid: next(iter(n)) for sid, n in units.items() if len(n) == 1})
