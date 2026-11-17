# Changelog

Every release opens with a **TL;DR**: a handful of short bullets, rewritten as a whole
whenever an entry is added. Entries are direct: symptom, cause, fix, with the issue link and
credit where there is one.

## v0.1.6 (unreleased)

### TL;DR
- The card's settings cog moves to the bottom right, next to the hardware capacity line
- Card labels: "Battery cycles per day (Average)" and "Projected SoH (Today)"
- Estimated Usable Capacity shows an icon again
- Bundled Store list: Huawei LUNA2000-7-S1 and LUNA2000-5-S0 names; S1 batteries up to 9 modules

### Changed
- Card: the settings cog is at the bottom right, on the same row as the hardware capacity check (on its own
  when the Health section is hidden), so the header only carries the warranty status.
- Card: "Cycles Per Day" is labelled "Battery cycles per day (Average)", without the C/day unit, and
  "Warranty Allows (today)" is "Projected SoH (Today)".
- Bundled Store list: the Huawei specs are named LUNA2000-7-S1 and LUNA2000-5-S0 (new spec IDs; existing
  setups keep their copied spec), and the LUNA2000-7-S1 and iStore IS-BATT-7000-ES allow 1-9 modules.

### Fixed
- Estimated Usable Capacity had no icon: `mdi:battery-analytics` (carried over from the YAML package) isn't a
  Material Design icon. It's now `mdi:battery-heart-outline`.

## v0.1.5 (2026-11-17)

### TL;DR
- New BatteryLedger dashboard card, installed with the integration: warranty use, throughput, cost and health
- The card compares your battery's actual SoH with what the warranty allows today
- Card settings (cost per kWh decimal places, sections shown) from the cog on the card

### Added
- BatteryLedger card (`custom:battery-ledger-card`), served and loaded by the integration, so there's
  nothing extra to install or add as a dashboard resource. Pick it from the card list and choose the
  setup. Sections:
  - Warranty: rings for warranty by time elapsed and by throughput used, the warranty driver, cycles per
    day and the warranty end date.
  - Throughput: remaining rated throughput counting down, with a marker for what's projected to be left
    when the warranty ends.
  - Cost: cost consumed to date, remaining value, and cost per kWh (rated and projected).
  - Health: the battery's reported SoH against the warranty curve (Estimated Usable Capacity) between the
    end-of-warranty capacity and 100%, plus the hardware capacity check and module figures where available.
  Tapping a figure opens its sensor. Admins change the card settings with the cog; they're saved by
  BatteryLedger for each setup, so every dashboard and device shows the same.
- Rated Throughput Used's `groups` attribute gives each group's `warranty_years`, `warranty_end_date` and
  `end_of_warranty_capacity_pct`.

## v0.1.4 (2026-11-17)

### TL;DR
- Model is now chosen after the brand, and only lists that brand's models
- Energy Manager offered for Sigenergy, Huawei, iStore and Sungrow, including its battery install date
- Sungrow setups can pick up sensors from mkaiser's Modbus package or Wingman3434's integration
- Huawei and iStore setups can pick up sensors from wlcrs's Huawei Solar integration
- Bundled Store list adds Huawei LUNA2000 and iStore batteries, and keeps only Sungrow's current warranty

### Fixed
- Store search offered every brand's models in the Model filter even with a brand chosen (e.g. Sungrow SBR
  and SBH under Sigenergy). Model is now its own step after the search, listing only the models among the
  matching batteries, and is skipped when there's just one.

### Added
- Energy Manager sensor profile: offered for Sigenergy, Huawei, iStore and Sungrow, after each brand's own
  integrations, since Energy Manager translates each vendor's integration into the same sensors. Setup fills in its lifetime discharged and charged energy,
  battery capacity and SoH sensors, and pre-fills the warranty start date from its
  `input_datetime.battery_install_date`.
- Sensor profiles can use fixed unique IDs and include an install-date entity
  from another platform (e.g. a helper). Any integration that keeps an install date pre-fills it the same way.
- Sungrow sensor profiles for mkaiser's Sungrow SHx Modbus YAML package and Wingman3434's Sungrow SHx Inverter
  integration: lifetime battery discharge and charge, battery capacity and SoH.
- Huawei Solar (wlcrs) sensor profile for Huawei and iStore batteries: lifetime battery discharge and charge,
  and rated capacity.

### Changed
- The bundled copy of the Store list includes the sensor profiles' default entity IDs, and adds the Huawei
  LUNA2000-5-E0 (S0) and LUNA2000-7-E1 (S1) and the iStore IS-BATT-5000-ES and IS-BATT-7000-ES for Australia.
- Sungrow SBH and SBR: only the current warranty (V8.0) is listed, as "SBH Battery Module 5.0 kWh" and
  "SBR Battery Module 3.2 kWh". The V7.1 specs are removed. Existing setups keep their copied spec; it no
  longer receives Store revisions because the spec IDs changed.

## v0.1.3 (2026-11-17)

### TL;DR
- The original YAML package's sensors now match it exactly: values, attributes and names
- Friendly names read "Battery …" for every brand
- Currency comes from Home Assistant's regional settings; choose $ or AUD style
- Setup name defaults to "<Brand> Battery", e.g. Sigenergy Battery
- New Cycles Per Day sensor, replacing the YAML package's battery_cycles_per_day
- Bundled Store list adds Sungrow SBR and SBH, and marks the Sigenergy specs verified

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
