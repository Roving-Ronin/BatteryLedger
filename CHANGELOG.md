# Changelog

Every release opens with a **TL;DR**: a handful of short bullets, rewritten as a whole
whenever an entry is added. Entries are direct: symptom, cause, fix, with the issue link and
credit where there is one.

## Unreleased

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
