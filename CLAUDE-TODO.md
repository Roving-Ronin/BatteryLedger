# CLAUDE-TODO

Work that's planned, waiting on something, or decided against, with what's needed to pick it up again. Read
this at the start of a session (CLAUDE.md points here); update it when an item moves, and delete items once
they're released. Newest decisions win: date each status line.

## Waiting

### BYD entity IDs on the Store site
**Status (2026-11-20):** BYD Battery Box doesn't set `has_entity_name`, so per-tower entities likely default to
`sensor.bms_1_state_of_charge` (in the Store's `default_entity_ids`), and the existing BMU defaults
(`sensor.battery_management_unit_…`) may be wrong. Display only (matching is by unique ID). Needs a BYD user's
real entity IDs.

## Later (not started)
- **SoH trend:** fill `soh_trend` / `soh_trend_years` (the export cost basis and attribute exist, unfilled):
  years until the warranty floor from the SoH history (reported or measured).
- **Export Cost tile** on the card: revisit after the maintainer has used it for a while.
- **Store: wanted sensor profiles** (Store README list): Growatt, Sofar, SolaX, Victron, GivEnergy, Fox ESS, Solis,
  SolarEdge, Tesla Powerwall, Enphase IQ, EcoFlow. Check each integration's source for unique IDs, SoH, SoC and
  per-tower counters before adding (CLAUDE.md rules).

## Decided against (and why)
- **Energy Pilot's control mappings, integration-name list and chemistry regex in the Store** (2026-11-20): only
  its capacity method and wanted-profiles idea were taken.
- **Per-tower energy from integrated power** for SoC-only towers (GoodWe battery 2, Deye P3 / ESPHome battery 2)
  (2026-11-20): at BatteryLedger's update interval it's noticeably less accurate; those are measured as one battery.
- **"Estimated Cycles Life"** (2026-11): dropped by the maintainer.
- **A custom label for skipping releases** (2026-11-20): repo uses GitHub's default labels only; `[skip release]`
  in the PR title or description instead.
