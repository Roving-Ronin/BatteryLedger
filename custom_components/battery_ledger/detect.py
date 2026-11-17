"""Find BatteryLedger's sensors using Store sensor profiles.

Sensors are matched by entity registry *unique ID* (stable, set by the integration),
never by entity ID (which users rename). Profile templates use placeholders for the
parts that differ between installs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, NamedTuple

PLACEHOLDERS = {
    "entry": r"[A-Za-z0-9]+",
    "device": r"[A-Za-z0-9_]+?",
    "prefix": r"[A-Za-z0-9_]+?",
    "plant": r"\d+",
    "inverter": r"\d+",
    "station": r"[A-Za-z0-9]+",
    "serial": r"[A-Za-z0-9]+",
}
# Placeholders that identify one system (plant); the others vary within it.
SYSTEM_KEYS = ("entry", "prefix", "plant")

SYSTEM_ROLES = ("discharged_energy", "charged_energy", "rated_capacity", "soh")
MODULE_ROLES = ("module_discharged_energy", "module_charged_energy", "module_rated_capacity",
                "module_soc", "module_soh")

_TOKEN = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


class RegistryEntity(NamedTuple):
    entity_id: str
    platform: str
    unique_id: str


@lru_cache(maxsize=256)
def compile_template(template: str) -> re.Pattern:
    out, pos = [], 0
    for m in _TOKEN.finditer(template):
        out.append(re.escape(template[pos:m.start()]))
        out.append(f"(?P<{m.group(1)}>{PLACEHOLDERS[m.group(1)]})")
        pos = m.end()
    out.append(re.escape(template[pos:]))
    return re.compile("^" + "".join(out) + "$")


@dataclass
class DetectedSystem:
    profile_id: str
    profile_name: str
    key: str
    # role -> (level, entity_id); only the preferred level that matched exactly one entity
    roles: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Roles where several inverter-level sensors matched and no plant-level one did
    ambiguous: list[str] = field(default_factory=list)
    # module ID (serial) -> role -> entity_id
    modules: dict[str, dict[str, str]] = field(default_factory=dict)
    modules_usable: bool = False

    @property
    def value(self) -> str:
        return f"{self.profile_id}|{self.key}"

    def label(self, multiple: bool) -> str:
        parts = [self.profile_name]
        if multiple:
            parts.append(self.key.replace("|", " "))
        found = f"{len(self.roles)} sensors"
        if self.modules:
            found += f", {len(self.modules)} battery modules"
        return f"{' · '.join(parts)} — found {found}"


def _system_key(groups: dict[str, str]) -> str:
    return "|".join(f"{k}={groups[k]}" for k in SYSTEM_KEYS if k in groups) or "default"


def detect(profile: dict, entities: Iterable[RegistryEntity]) -> list[DetectedSystem]:
    """All systems of this profile's integration found among the entities."""
    platform = profile["integration"]["platform"]
    candidates = [e for e in entities if e.platform == platform and e.unique_id]
    systems: dict[str, DetectedSystem] = {}
    matches: dict[tuple[str, str], list[tuple[int, str, str]]] = {}  # (key, role) -> [(rule idx, level, entity)]

    def system(key: str) -> DetectedSystem:
        return systems.setdefault(key, DetectedSystem(profile["id"], profile["name"], key))

    for role, rules in profile["roles"].items():
        for idx, rule in enumerate(rules):
            pattern = compile_template(rule["unique_id"])
            for ent in candidates:
                m = pattern.match(ent.unique_id)
                if not m:
                    continue
                groups = m.groupdict()
                key = _system_key(groups)
                if role in MODULE_ROLES:
                    system(key).modules.setdefault(groups["serial"], {}).setdefault(role, ent.entity_id)
                else:
                    system(key)
                    matches.setdefault((key, role), []).append((idx, rule["level"], ent.entity_id))

    for (key, role), found in matches.items():
        best = min(i for i, _, _ in found)
        top = [(lvl, eid) for i, lvl, eid in found if i == best]
        if len(top) == 1:
            systems[key].roles[role] = top[0]
        else:
            systems[key].ambiguous.append(role)
    return [s for s in systems.values() if s.roles or s.modules]


def assign_modules(
    modules: dict[str, float | None],
    groups: list[tuple[float | None, int]],
    tolerance: float = 0.03,
) -> tuple[dict[str, int], list[str]]:
    """Assign modules to battery groups by their rated capacity.

    modules: module ID -> rated kWh reported (None if unknown)
    groups: per group (rated kWh per unit from the spec, configured units)
    Returns (module ID -> group index, problems).
    """
    out: dict[str, int] = {}
    problems: list[str] = []
    for mid, kwh in sorted(modules.items()):
        if len(groups) == 1:
            out[mid] = 0
            continue
        if kwh is None:
            problems.append(f"module {mid}: rated capacity unknown, can't tell which battery group it belongs to")
            continue
        fits = [i for i, (cap, _) in enumerate(groups) if cap and abs(kwh - cap) <= cap * tolerance]
        if len(fits) == 1:
            out[mid] = fits[0]
        else:
            problems.append(f"module {mid}: rated {kwh:g} kWh matches {len(fits)} battery groups")
    for i, (_, units) in enumerate(groups):
        n = sum(1 for g in out.values() if g == i)
        if n != units:
            problems.append(f"battery group {i + 1}: found {n} modules, configured {units}")
    return out, problems
