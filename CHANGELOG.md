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
- Bundled Store list adds the Sigenergy SigenStor Neo BAT 6.0 and BAT 8.0
- Bundled Store list adds AlphaESS batteries, with sensors from senalse's AlphaESS Modbus TCP integration or
  Energy Manager
- Bundled Store list adds Deye batteries, with sensors from davidrapan's Solarman, Lewa-Reka's ESPHome Deye
  Inverter or Energy Manager
- Bundled Store list adds GoodWe batteries, with sensors from the GoodWe integration (ET-family hybrids) or
  Energy Manager
- Bundled Store list adds BYD Battery-Box Premium and Fronius Reserva, with sensors from redpomodoro's BYD Battery
  Box or Fronius Modbus integrations, or Energy Manager

### Changed
- Card: the settings cog is at the bottom right, on the same row as the hardware capacity check (on its own
  when the Health section is hidden), so the header only carries the warranty status.
- Card: "Cycles Per Day" is labelled "Battery cycles per day (Average)", without the C/day unit, and
  "Warranty Allows (today)" is "Projected SoH (Today)".
- Bundled Store list: the Huawei specs are named LUNA2000-7-S1 and LUNA2000-5-S0 (new spec IDs; existing
  setups keep their copied spec), and the LUNA2000-7-S1 and iStore IS-BATT-7000-ES allow 1-9 modules.
- Bundled Store list: Sigenergy has a second model, SigenStor Neo, with the Neo BAT 6.0 (6.02 kWh total)
  and Neo BAT 8.0 (7.52 kWh total), 1-6 modules. Sigenergy setups now ask for the Model after the brand.
- Bundled Store list: AlphaESS (Australia), with the SMILE-M5 (SMILE-M-BAT-13.9P, SMILE-M-BAT-5P), SMILE-G3
  (SMILE-G3-BAT-10.1P, SMILE-G3-BAT-4.0S), SMILE-T10-HV (SMILE-BAT-8.2PH) and SMILE5 (SMILE-BAT-13.3P,
  SMILE-BAT-10.1P, SMILE5-BAT). Energy Manager is offered for AlphaESS setups.
- Sensor profile for senalse's AlphaESS Modbus TCP integration: lifetime battery charge and discharge,
  battery capacity (disabled by default in that integration; enable it for the hardware capacity check) and SoH.
- Bundled Store list: Deye (Australia), with the Spring SE (SE-G5.1 Pro-B), Spring AI (AI-W5.1-B), RW (RW-M6.1-B,
  RW-F10.2), BOS-G (BOS-GM5.1, 3-12 modules) and BOS-G Pro (BOS-G-Pack5.1, 5-17 modules). The BOS-G warranties
  give throughput per system size, which BatteryLedger looks up by module count. Energy Manager is offered for Deye.
- Sensor profiles for Deye: davidrapan's Solarman and Lewa-Reka's ESPHome Deye Inverter (lifetime battery charge
  and discharge). Solarman's Battery SOH and Battery Capacity are its own estimates, so they aren't used.
- Sensor profiles can use a `{mac}` placeholder for ESPHome devices, whose unique IDs start with the device's MAC
  address. Each ESPHome inverter is found as its own system.
- Bundled Store list: GoodWe (Australia and New Zealand), with the Lynx Home F (LX F3.3-H, throughput table per
  tower), Lynx Home F G2 (LX F3.2-20), Lynx Home U (LX U5.4-L) and Lynx U G3 (LX U5.0-30).
- Sensor profile for GoodWe (Home Assistant core and mletenay's custom version share the domain and unique IDs):
  lifetime battery charge and discharge and the BMS state of health, on ET/EH/BT/BH hybrids. GoodWe's ES-family
  inverters don't report lifetime battery energy.
- Huawei Solar (wlcrs) profile v2: uses the EMMA's site-wide battery totals and rated ESS capacity (or a
  SmartLogger's, with its state of health) before a single inverter's Batteries device, so a cascaded stack of up
  to 3 inverters is tracked as one system.
- Bundled Store list: BYD Battery-Box Premium HVS (2-5 modules) and HVM (3-8 modules), Australia, 60% EOL with
  throughput tables per tower; Fronius Reserva (2-5 modules, 70%) and Reserva Pro (3-8 modules, 75%), Australia and
  New Zealand, throughput tables per tower from Fronius's battery warranty (EN_0326, country group 3).
- Sensor profiles: redpomodoro's BYD Battery Box (battery BMS: lifetime charge and discharge, total capacity, state of
  health) and Fronius Modbus (GEN24 storage charging and discharging lifetime energy, storage capacity). The core
  Fronius integration has no battery energy totals.
- README: the integrations BatteryLedger knows are listed by battery brand.

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
