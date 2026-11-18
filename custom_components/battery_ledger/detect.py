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
    "mac": r"[0-9A-Fa-f]{2}(?::?[0-9A-Fa-f]{2}){5}",  # ESPHome: AA:BB:CC:DD:EE:FF or aabbccddeeff
}
# Placeholders that identify one system (plant); the others vary within it.
SYSTEM_KEYS = ("entry", "prefix", "plant", "mac")

SYSTEM_ROLES = ("discharged_energy", "charged_energy", "rated_capacity", "soh", "install_date",
                "install_cost", "install_date_2", "install_cost_2", "brand", "module_count", "tower_count")
# Kept for every inverter (not narrowed to one entity): they describe the batteries on each inverter.
INVERTER_ROLES = ("inverter_model", "inverter_pack_count", "inverter_rated_capacity", "pack_serial")
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
    # inverter key -> role -> entity_ids (pack_serial has one per pack position)
    inverters: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    @property
    def value(self) -> str:
        return f"{self.profile_id}|{self.key}"

    def label(self, multiple: bool) -> str:
        """Data-only label: profile name, plus the system key when one integration has several."""
        return f"{self.profile_name} · {self.key.replace('|', ' ')}" if multiple else f"{self.profile_name} ✓"


def _system_key(groups: dict[str, str]) -> str:
    return "|".join(f"{k}={groups[k]}" for k in SYSTEM_KEYS if k in groups) or "default"


def _inverter_key(groups: dict[str, str]) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(groups.items()) if k not in SYSTEM_KEYS) or "default"


def detect(profile: dict, entities: Iterable[RegistryEntity]) -> list[DetectedSystem]:
    """All systems of this profile's integration found among the entities."""
    default_platform = profile["integration"]["platform"]
    entities = [e for e in entities if e.unique_id]
    systems: dict[str, DetectedSystem] = {}
    matches: dict[tuple[str, str], list[tuple[int, str, str]]] = {}  # (key, role) -> [(rule idx, level, entity)]

    def system(key: str) -> DetectedSystem:
        return systems.setdefault(key, DetectedSystem(profile["id"], profile["name"], key))

    for role, rules in profile["roles"].items():
        for idx, rule in enumerate(rules):
            pattern = compile_template(rule["unique_id"])
            # A rule can name its own platform, e.g. input_datetime for an install-date helper.
            platform = rule.get("platform", default_platform)
            for ent in (e for e in entities if e.platform == platform):
                m = pattern.match(ent.unique_id)
                if not m:
                    continue
                groups = m.groupdict()
                key = _system_key(groups)
                if role in MODULE_ROLES:
                    system(key).modules.setdefault(groups["serial"], {}).setdefault(role, ent.entity_id)
                elif role in INVERTER_ROLES:
                    found = system(key).inverters.setdefault(_inverter_key(groups), {}).setdefault(role, [])
                    if ent.entity_id not in found:
                        found.append(ent.entity_id)
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
    return [s for s in systems.values() if s.roles or s.modules or s.inverters]


def assign_modules(
    modules: dict[str, float | None],
    groups: list[tuple[float | None, int]],
    tolerance: float = 0.03,
) -> tuple[dict[str, int], list[str], list[tuple[int, int]]]:
    """Assign modules to battery groups by their rated capacity.

    modules: module ID -> rated kWh reported (None if unknown)
    groups: per group (rated kWh per unit from the spec, configured units)
    Returns (module ID -> group index, unassigned module IDs, per group (found, configured)).
    """
    out: dict[str, int] = {}
    unassigned: list[str] = []
    for mid, kwh in sorted(modules.items()):
        if len(groups) == 1:
            out[mid] = 0
            continue
        fits = [i for i, (cap, _) in enumerate(groups)
                if kwh is not None and cap and abs(kwh - cap) <= cap * tolerance]
        if len(fits) == 1:
            out[mid] = fits[0]
        else:
            unassigned.append(mid)
    counts = [(sum(1 for g in out.values() if g == i), units) for i, (_, units) in enumerate(groups)]
    return out, unassigned, counts
