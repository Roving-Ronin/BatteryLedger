# CLAUDE-TODO

Work that's planned, waiting on something, or decided against, with what's needed to pick it up again. Read
this at the start of a session (CLAUDE.md points here); update it when an item moves, and delete items once
they're released. Newest decisions win: date each status line.

## Waiting

### v0.4.0: Savings and payback
**Status (2026-11-20):** designed; waiting on Home Energy Advisor (HEA) for a lifetime installation savings
sensor. Requested in [HEA discussion #58](https://github.com/consultingtedds/ha-home-energy-advisor/discussions/58)
(posted 2026-11-20). Battery-only payback could be built now from HEA's Battery Savings; the maintainer hasn't
said go yet.

**Design (agreed in outline):** Configure → **Savings and payback**, optional:
- What to measure: **Battery only** (against the battery groups' costs) or **Whole installation** (against
  battery costs + an **Other system costs** amount: panels, inverter, installation).
- Savings sensor (detected, changeable); for Whole installation, until HEA's new sensor exists, Cost Savings +
  export earnings; optional battery losses cost to subtract.
- **Returns before these sensors started**: a typed amount added on (the sensors only count from their setup).
- Sensors: `savings_to_date`, `payback_date`, `net_position` (savings − investment; attributes: projected savings
  and ROI % at warranty end and EoSL).
- Card: a new section **ROI** (Return on Investment), internal key `roi` (section names and keys match, as since
  0.3.2: `usage` = Usage & Throughput, `financials` = Financials); on/off in the card settings like the others.
  Its place among the sections is to settle with the maintainer when it's built (2026-11-20).
- Rate: average since BatteryLedger first saw the sensor (kept in storage); first 30 days: total ÷ days since
  install, `low_confidence`; projections `low_confidence` until a year of data (seasons).
- Per setup, not per battery group (savings are whole-battery). Refuse a currency that isn't HA's.

**What the HEA sensor should be** (as requested): a "Plan without solar or battery" marker beside HEA's current
plan, and a running total of [that plan's *Without solar or battery* cost] − [current plan's actual Total, daily
charges and export income included], knowing which plan was current when, starting from the earliest statistics.
Worked example, 19 Nov 2026: Red Energy without solar/battery $16.93 − Covau actual $0.07 = **$16.86** (Covau's
own "saves $16.28" leaves out the $0.58 from the better plan). When it lands: check its unique ID, state class,
attributes (start date, days, gaps) and whether it can fall; then Whole installation reads it alone (export income
is already in plan totals) and the typed amount only covers before HA's statistics.

**Facts checked (HEA v1.6.1 source, MIT):**
- Whole Home device sensors, platform `home_energy_advisor`, unique ID `{entry_id}_whole_home_<key>`:
  `battery_savings` (monetary, state_class total, **can fall**: battery charged dear / discharged cheap),
  `cost_savings` (solar + battery vs grid). Battery Losses device: energy and Actual Cost of what the battery
  never gave back (measured, no efficiency assumed).
- HEA's totals start when HEA was set up (`recorded_baseline.py` only restores after restarts). Its plan
  comparison prices from long-term statistics, so past periods are reachable there.
- HEA takes a "Battery usable capacity sensor": BatteryLedger's `measured_usable_capacity` can be it for
  batteries that don't publish one (Huawei, Deye). Mention in both READMEs when v0.4.0 lands.
- Home Assistant's export compensation sensor (energy integration, `components/energy/sensor.py`): created when
  an export price is set in the Energy dashboard; entity ID `<export meter>_compensation`, unique ID
  `<export meter's registry entry id>_grid_compensation` (or the user's own `stat_compensation` in the grid's
  `flow_to`). State class total; **resets to 0 when its energy meter resets**, so accumulate increases across
  resets rather than reading the value. Counts from when the price was set, not lifetime. Several export meters:
  add them up. Read the Energy prefs via `energy.data.async_get_manager(hass).data["energy_sources"]`.

### Auto Release: first real run
**Status (2026-11-20):** merged in PR #20; v0.3.1 was released by hand before it. On the next `vX.Y.Z: …`
PR merge, check the Auto Release run created the release, `battery_ledger.zip` is attached and `manifest.json` on
main was bumped. zizmor's `self-repository` finding is ignored on the two local `uses:` lines on purpose.

### BYD entity IDs on the Store site
**Status (2026-11-20):** BYD Battery Box doesn't set `has_entity_name`, so per-tower entities likely default to
`sensor.bms_1_state_of_charge` (in the Store's `default_entity_ids`), and the existing BMU defaults
(`sensor.battery_management_unit_…`) may be wrong. Display only (matching is by unique ID). Needs a BYD user's
real entity IDs.

## Later (not started)
- **SoH trend:** fill `soh_trend` / `soh_trend_years` (the export cost basis and attribute exist, unfilled):
  years until the warranty floor from the SoH history (reported or measured).
- **Export Cost tile** on the card: revisit after the maintainer has used it for a while.
- **Per-group cost per kWh** (cost sensors are per setup today).
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
