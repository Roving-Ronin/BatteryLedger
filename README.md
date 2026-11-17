<p align="center"><img src="images/banner.png" alt="BatteryLedger: ESS Health &amp; Asset Tracking by Roving-Ronin" width="582"></p>

# BatteryLedger

Home Assistant custom integration to track Energy Storage System (ESS) battery health, throughput warranty,
degradation, cost per kWh, and remaining asset value.

Battery specifications come from the community [BatteryLedger Store](https://roving-ronin.github.io/BatteryLedger-Store/)
([repo](https://github.com/Roving-Ronin/BatteryLedger-Store)), so you pick your battery instead of typing in
warranty figures.

## Installation

HACS → ⋮ → Custom repositories → `https://github.com/Roving-Ronin/BatteryLedger` (Integration), install
**BatteryLedger**, restart Home Assistant, then Settings → Devices & services → Add integration → BatteryLedger.

## Setup

1. **Find your battery:** search the Store by text, brand, region and phase (single / three), or enter the details
   from your datasheet manually. The Store list is downloaded once a day (no account needed) and a copy ships with
   each release for offline use.
2. **Battery group:** number of modules/units and the warranty start date. Add another group for each extra battery
   type, or for modules added later (e.g. BAT 8.0 + BAT 10.0).
3. **Inverter integration:** BatteryLedger looks for your inverter integration's sensors using the Store's
   *sensor profiles* (matched by entity registry unique ID, so renamed entities still work) and lists the
   integrations it knows for your battery brand. Currently: TypQxQ's Sigenergy Local Modbus and sigenergy2mqtt.
4. **Battery modules** (when available, e.g. sigenergy2mqtt with the Sigen Cloud API enabled): per-module
   discharge counters are assigned to your battery groups by each module's rated capacity, and each module is
   tracked against its own warranty limit.
5. **System:** battery cost and currency, and the sensors (filled in from step 3 if detected): lifetime
   **charged** and/or **discharged** energy, and optionally rated capacity (hardware check) and battery state of
   health.

Cost, currency and sensors can be changed later under **Configure**.

## Sensors

| Sensor | What it shows |
|---|---|
| Warranted throughput | Total warranted energy throughput for the configured units |
| Throughput used / remaining | Energy counted against the warranty so far, and what's left |
| Warranty throughput used | Throughput used as % of the limit |
| Warranty time elapsed | Time since warranty start as % of the warranty period |
| Projected warranty throughput | Throughput by end of warranty at the average rate so far (capped at the limit) |
| Cost per kWh (warranted / projected) | Battery cost ÷ warranted or projected throughput |
| Cost consumed / Remaining value | Cost apportioned to throughput used, and the remainder |
| Initial usable capacity | Usable capacity at beginning of life |
| Warranty floor capacity / health | Minimum capacity the warranty guarantees today (see below) |
| Warranty driver | Whether age or throughput is using up the warranty faster |
| Warranty status | On track, using throughput faster than time, or ended |
| Hardware check | Whether the inverter's reported capacity matches the configured units (if a sensor is set) |
| Health above warranty floor | Reported state of health minus the warranty floor, in percentage points (if a SoH sensor is set) |
| Most-used module throughput | Highest per-module share of its warranty throughput, with every module in the attributes (module tracking) |
| Module SoC spread | Highest minus lowest module state of charge right now (module tracking) |

## What the numbers mean (and don't)

- **Warranty floor, not state of health.** Warranties promise e.g. 70% capacity after 10 years *or* a throughput
  limit, whichever comes first. BatteryLedger takes whichever is further along and interpolates from 100% down to
  that end-of-life figure. That is the capacity the manufacturer guarantees at this point, not a measurement of
  your battery's actual health.
- **Charged vs discharged.** Some warranties count throughput as charged energy, some as discharged, and many don't
  say. When the warranty doesn't say, or the matching sensor isn't configured, BatteryLedger uses charged energy,
  which is always the larger figure, so it errs towards the warranty running out sooner. The sensor attributes say
  which counter was used.
- **Multiple battery groups** sharing one plant-level energy counter can't be separated exactly. Energy is split by
  usable capacity × days in service, which assumes broadly even use.
- **Per-module tracking** measures each module against its own limit (Sigen's throughput warranty is per
  module), so one heavily used module shows up even when the system average looks fine. It needs a counter for
  every configured module and a per-unit warranty counted on discharged energy; otherwise the plant counter is
  used. Cloud data is unofficial and can lag; the `module_total_vs_plant_pct` attribute compares the module
  total with the plant counter.
- **SoC spread** is a snapshot. A gap that persists in the history graph can point to imbalance, but a single
  reading means little, and BatteryLedger doesn't label a module weak from it.
- **Reported SoH** is the battery management system's own estimate; BatteryLedger shows it against the warranty
  floor but can't verify it.
- **Projections** are unreliable in the first month (`low_confidence` attribute).
- **Spec updates:** your chosen spec is copied into your setup. If the Store later revises it, a Repairs notice
  shows what changed and lets you accept it, so figures never change silently.

## Requirements

Home Assistant 2026.3 or newer shows BatteryLedger's own icon. Older versions work but show a placeholder icon.

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest -q
```

`tests/test_ledger.py` covers the calculations without Home Assistant; `tests/test_integration.py` runs the setup
flow, sensors and Store-revision repairs in a test Home Assistant instance.

The bundled Store snapshot is `custom_components/battery_ledger/data/index_snapshot.json`; refresh it from the
Store's published `index.json` before each release.
