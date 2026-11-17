# Changelog

Every release opens with a **TL;DR**: a handful of short bullets, rewritten as a whole
whenever an entry is added. Entries are direct: symptom, cause, fix, with the issue link and
credit where there is one.

## v0.1.2 (unreleased)

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
