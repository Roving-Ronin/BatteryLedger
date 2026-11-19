"""Export a setup to a JSON file and read it back (a new Home Assistant server without a backup restore).

Pure: no Home Assistant imports. The file holds the battery groups (copied specs, units, warranty start dates,
costs), the name, currency style and sensor profile, the source sensors chosen, which battery module (by
serial) is in which group, and the card settings. Module serials let a restore keep assignments that capacity
alone can't make (e.g. two groups of the same model); sensor entity IDs are used where they exist on the new
server. The file is the user's own: it isn't sent anywhere (diagnostics, which may be shared, leave serials
and costs out).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from .const import (
    CONF_COST,
    CONF_CAPACITY_ENTITY,
    CONF_CHARGED_ENTITY,
    CONF_CURRENCY_STYLE,
    CONF_DISCHARGED_ENTITY,
    CONF_GROUPS,
    CONF_INSTALL_DATE,
    CONF_MODULES,
    CONF_PROFILE,
    CONF_SOH_ENTITY,
    CONF_SPEC,
    CONF_UNITS,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    MOD_GROUP,
    MOD_ID,
)

SENSOR_KEYS = (CONF_CHARGED_ENTITY, CONF_DISCHARGED_ENTITY, CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY)

EXPORT_MARKER = "battery_ledger_export"
EXPORT_FORMAT = 1

# Error codes (translated in strings.json under config.error)
ERR_NOT_JSON = "import_not_json"
ERR_NOT_EXPORT = "import_not_export"
ERR_NEWER = "import_newer"
ERR_INVALID = "import_invalid"


class TransferError(ValueError):
    """The pasted text isn't a usable export; args[0] is an error code (ERR_*)."""


def build_export(title: str, data: dict[str, Any], options: dict[str, Any], today: date,
                 card_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    current = {**data, **options}
    groups = []
    for g in data.get(CONF_GROUPS) or []:
        group = {CONF_SPEC: g[CONF_SPEC], CONF_UNITS: g[CONF_UNITS], CONF_INSTALL_DATE: g[CONF_INSTALL_DATE]}
        if g.get(CONF_COST) is not None:
            group[CONF_COST] = g[CONF_COST]
        groups.append(group)
    return {
        EXPORT_MARKER: EXPORT_FORMAT,
        "entry_version": f"{CONFIG_ENTRY_VERSION}.{CONFIG_ENTRY_MINOR_VERSION}",
        "exported": today.isoformat(),
        "name": title,
        CONF_CURRENCY_STYLE: current.get(CONF_CURRENCY_STYLE),
        CONF_PROFILE: data.get(CONF_PROFILE),
        CONF_GROUPS: groups,
        "sensors": {k: current[k] for k in SENSOR_KEYS if current.get(k)},
        CONF_MODULES: [{MOD_ID: m[MOD_ID], MOD_GROUP: m[MOD_GROUP]} for m in data.get(CONF_MODULES) or []],
        "card_settings": card_settings,
    }


def export_filename(slug: str, today: date) -> str:
    return f"battery-ledger-{slug or 'setup'}-{today.isoformat()}.json"


def export_text(export: dict[str, Any]) -> str:
    return json.dumps(export, indent=2, ensure_ascii=False)


def parse_export(text: str) -> dict[str, Any]:
    """The export's contents, checked. Raises TransferError."""
    try:
        export = json.loads(text)
    except (TypeError, ValueError) as err:
        raise TransferError(ERR_NOT_JSON) from err
    if not isinstance(export, dict) or EXPORT_MARKER not in export:
        raise TransferError(ERR_NOT_EXPORT)
    try:
        fmt = int(export[EXPORT_MARKER])
        major, minor = (int(x) for x in str(export.get("entry_version", "1.0")).split("."))
    except (TypeError, ValueError) as err:
        raise TransferError(ERR_INVALID) from err
    # Refuse what a newer BatteryLedger wrote, rather than guess at it.
    if fmt > EXPORT_FORMAT or (major, minor) > (CONFIG_ENTRY_VERSION, CONFIG_ENTRY_MINOR_VERSION):
        raise TransferError(ERR_NEWER)
    groups = export.get(CONF_GROUPS)
    if not isinstance(groups, list) or not groups:
        raise TransferError(ERR_INVALID)
    checked = []
    for g in groups:
        try:
            spec = g[CONF_SPEC]
            if not isinstance(spec, dict) or not all(k in spec for k in ("brand", "model", "capacity", "warranty")):
                raise TransferError(ERR_INVALID)
            group = {CONF_SPEC: spec, CONF_UNITS: int(g[CONF_UNITS]),
                     CONF_INSTALL_DATE: date.fromisoformat(g[CONF_INSTALL_DATE]).isoformat()}
            if g.get(CONF_COST) is not None:
                group[CONF_COST] = float(g[CONF_COST])
        except (KeyError, TypeError, ValueError) as err:
            raise TransferError(ERR_INVALID) from err
        checked.append(group)
    sensors = export.get("sensors") if isinstance(export.get("sensors"), dict) else {}
    modules = {}
    for m in export.get(CONF_MODULES) or []:
        if isinstance(m, dict) and isinstance(m.get(MOD_ID), str) and isinstance(m.get(MOD_GROUP), int) \
                and 0 <= m[MOD_GROUP] < len(checked):
            modules[m[MOD_ID]] = m[MOD_GROUP]
    name = export.get("name")
    card = export.get("card_settings")
    return {
        "name": name if isinstance(name, str) else None,
        CONF_CURRENCY_STYLE: export.get(CONF_CURRENCY_STYLE),
        CONF_PROFILE: export.get(CONF_PROFILE) if isinstance(export.get(CONF_PROFILE), str) else None,
        CONF_GROUPS: checked,
        "sensors": {k: v for k, v in sensors.items() if k in SENSOR_KEYS and isinstance(v, str)},
        CONF_MODULES: modules,  # module serial -> group index
        "card_settings": card if isinstance(card, dict) else None,
    }
