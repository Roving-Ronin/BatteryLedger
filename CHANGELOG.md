# Changelog

Every release opens with a **TL;DR**: a handful of short bullets, rewritten as a whole
whenever an entry is added. Entries are direct: symptom, cause, fix, with the issue link and
credit where there is one.

## v0.1.3 (unreleased)

### TL;DR
- The original YAML package's sensors now match it exactly: values, attributes and names
- Friendly names read "Battery …" for every brand
- Currency comes from Home Assistant's regional settings; choose $ or AUD style
- Setup name defaults to "<Brand> Battery", e.g. Sigenergy Battery
- New Cycles Per Day sensor, replacing the YAML package's battery_cycles_per_day
- Model is now chosen after the brand, and only lists that brand's models

### Fixed
- Store search offered every brand's models in the Model filter even with a brand chosen (e.g. Sungrow SBR
  and SBH under Sigenergy). Model is now its own step after the search, listing only the models among the
  matching batteries, and is skipped when there's just one.

### Changed
- The nine sensors carried over from the original YAML package are now identical to it, so templates and
  dashboards built on the package work unchanged:
  - `degradation_driver` / `warranty_status` attributes are back to the package's text ("Age (Time Elapsed)",
    "On Track / Normal" ...) instead of codes.
  - `hardware_capacity_validation` reports "Match Verified" / "Mismatch Detected".
  - No extra attributes: `groups`, `notes`, `average_daily_kwh` and `low_confidence` moved to
    `rated_throughput_used`; the attribution line is gone; no `device_class` on these sensors.
  - Friendly names are "Battery" + the package's Title Case names (e.g. "Battery Estimated Usable Capacity")
    whatever the brand, instead of starting with the setup's name.
- Removed five sensors that duplicated the package's attributes: `rated_life_used`, `estimated_remaining_value`,
  `remaining_usable_capacity`, `degradation_driver` and `warranty_status`. Use the attributes on
  *Cost Consumed To Date* and *Estimated Usable Capacity* instead, as in the package. Existing setups have these
  entities removed automatically.
- Added `sensor.battery_ledger_cycles_per_day` (C/day): energy counted ÷ days since the warranty start ÷ rated
  capacity, worked out from the install date and the inverter's rated capacity (or the spec), so the YAML
  package's `battery_cycles_per_day`, `battery_age_days` and `battery_capacity` helpers aren't needed.
- The currency field is gone from setup and Configure: BatteryLedger uses the currency set in Settings →
  System → General. Instead you choose the symbol (`$`, `$/kWh`, as in the YAML package; the default)
  or the code (`AUD`, `AUD/kWh`). With the code, cost consumed and remaining value are money sensors that Home
  Assistant formats in your locale's currency style.
- Setups made before 0.1.3 keep the currency they were given.
- The default setup name is capitalised: "Sigenergy Battery" rather than "Sigenergy battery".

## v0.1.2 (2026-11-17)

### TL;DR
- Sensor names back to the original YAML package's, as `sensor.battery_ledger_*`
- Original attributes restored for existing dashboards
- 0.1.1 entities renamed automatically

### Changed
- Entity IDs and names follow the original YAML package with `battery_ledger_` instead of `sigen_battery_`
  (e.g. `sensor.battery_ledger_total_rated_throughput`). 0.1.1 renamed them, which broke dashboards built
  on the package.
- Restored the package's attributes: `total_pack_count`, `percent_of_rated_life_used`,
  `estimated_remaining_value`, `remaining_usable_kwh`, `degradation_driver`, `warranty_status`,
  `configured_rated_kwh`, `reported_hardware_kwh`. The values also remain separate sensors.
- Setups made with 0.1.1 are migrated: each sensor keeps its history and moves to the new entity ID,
  unless you had renamed it yourself.

## v0.1.1 (2026-11-17)

### TL;DR
- First release: battery warranty, health and cost tracking from a community spec Store
- Find your battery by brand, model, region and phase; mix models in one system
- Inverter sensors filled in automatically (TypQxQ Local Modbus, sigenergy2mqtt)
- Optional per-module tracking, SoC spread and reported SoH vs warranty floor

### Added
- Store lookup with search and Brand, Model (e.g. SigenStor / Neo), Region and Phase filters; manual entry
  for batteries not in the Store.
- Several battery models per system, each with its own unit count and warranty start date.
- Sensors: warranted / used / remaining throughput, warranty time elapsed, projected throughput,
  cost per kWh (warranted and projected), cost consumed, remaining value, initial and warranty floor
  capacity, warranty driver and status, hardware check.
- Sensor profiles from the Store detect the inverter integration's sensors by unique ID.
- Per-module throughput from sigenergy2mqtt's Sigen Cloud sensors: each module against its own
  warranty limit, most-used module, module SoC spread.
- Reported state of health compared with the warranty floor.
- Store spec revisions are offered through Repairs instead of changing figures silently.
- Brand icon and logo (Home Assistant 2026.3+).

## v0.1.0 (2026-11-17)

First published build. Superseded the same day by v0.1.1, which adds the Model filter, mixed battery
models in one setup, Store refresh result steps and the issue automation.
