# CLAUDE-TODO

Work that's planned, waiting on something, or decided against, with what's needed to pick it up again. Read
this at the start of a session (CLAUDE.md points here); update it when an item moves, and delete items once
they're released. Newest decisions win: date each status line.

## Waiting

### v0.4.0: Savings and payback
**Status (2026-11-21):** HEA 1.7.0 answered #58 with an **action, not a sensor** (its ADR-0047): see "HEA 1.7.0"
below. Nothing left to wait for; design to confirm with the maintainer, then build.

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
- Sensors (settled 2026-11-21; separate sensors where unit / device class differ, breakdowns as attributes):
  - `savings_to_date` (money, running total): `today`, `this_week`, `this_month`, `this_year`, `before_figures`,
    `days_counted` / `days_since_install`, `plan_current`, `plan_without`, `calculated`.
  - `return_on_investment` (%: (savings − investment) ÷ investment): `investment`, `net_position`,
    `roi_at_warranty_end`, `roi_at_eosl`.
  - `break_even_date` (date device class): `days_to_go`, `daily_rate`, `confidence`.
  - `projected_lifetime_savings` (money, at EoSL at the rate so far): `at_warranty_end`, `at_eosl`, `per_year`.
- Savings stored **per day** (one `compare_plans` call per day; backfill slowly in the background; redo the last
  ~35 days nightly; weekly, one call per month compared with the sum of its days, redoing only months that differ;
  redo everything when the chosen plan changes). Week / month / year are sums of days.
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

**HEA 1.7.0 (checked 2026-11-21, source; ADR-0042, ADR-0047):**
- No savings sensor, by decision (ADR-0047: the figure is recomputed from inputs that get corrected later, so a
  kept history would go stale). Instead the action `home_energy_advisor.compare_plans` (`start`, `end` datetimes in
  local time; `supports_response` only; refuses a period starting in the future or end ≤ start) returns, for the
  period: `days` (covered), `hours`, `imported_kwh`, `exported_kwh`, `left_out` (stretches with no data: `from`,
  `to`, `source`, `kwh`) and `plans`: each with `id` (subentry ID, stable), `name`, `current` (true for exactly
  one: the plan the household is on, now created by HEA and priced at the Energy Dashboard's own prices,
  `follows_prices`), `total`, `energy`, `export_credit`, `daily_charges`, `breakdown`, and
  **`without_installation`**: that plan's cost of everything the house used, bought from the grid, daily charges
  included (absent with no generation or battery). A plan can instead have `no_price` or `incomplete`;
  the current plan can have `daily_charge_missing` (HEA holds its differences until answered).
- So the installation saving for a period = [chosen "no solar or battery" plan's `without_installation`] −
  [current plan's `total`]. There is **no "plan without solar or battery" marker in HEA**: BatteryLedger has to
  let the user pick it (store the plan `id`). 19 Nov 2026 check: Red Energy 16.93 − Covau 0.07 = 16.86.
- **Plan for BatteryLedger:** call the action itself rather than wait for a sensor. Work in calendar months from
  the installation date (or HA's earliest statistics): one call per month, results kept in storage per month
  with `days` and `left_out`; refresh the current month (and last month, for late data) daily, and recompute the
  whole history now and then (e.g. weekly, and when the chosen plan changes) so corrections in HEA flow through.
  Savings to date = sum of months + the typed "before these figures" amount. Coverage (days counted vs days since
  install) becomes an attribute and a confidence note.
- HEA's own roadmap after 1.7.0 lists **HEA-242 (payback)** and HEA-272 (clear figures for a period). Watch for
  overlap: if HEA ships payback, BatteryLedger's ROI should read the same figures rather than differ from them.

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
