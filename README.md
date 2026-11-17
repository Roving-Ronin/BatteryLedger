<p align="center"><img src="images/banner.png" alt="BatteryLedger: ESS Health &amp; Asset Tracking by Roving-Ronin" width="582"></p>

[![Marketplace][marketplace-badge]][marketplace-url]
[![release][release-badge]][release-url]
[![downloads][downloads-badge]][release-url]
[![stars][repo-stars-badge]][repo-url]
[![license][license-badge]][license-url]
[![installs][installs-badge]][installs-url]

[![maintained][maintained-badge]][commits-url]
[![activity][activity-badge]][commits-url]
[![Validate][validate-badge]][validate-url]
[![Tests][tests-badge]][tests-url]

___

Home Assistant custom integration to track Energy Storage System (ESS) battery health, throughput warranty,
degradation, cost per kWh, and remaining asset value.

Battery specifications come from the community [BatteryLedger Store](https://roving-ronin.github.io/BatteryLedger-Store/)
([repo](https://github.com/Roving-Ronin/BatteryLedger-Store)), so you pick your battery instead of typing in
warranty figures.

## Installation Methods:

BatteryLedger isn't in the default list yet, so add it as a custom repository first.

### Marketplace (Home Assistant 2026.11 and newer)

[![Open this repository in the Marketplace][marketplace-button]][marketplace-url]

Or add it manually:

1. Go to **Settings → Marketplace**, open the ⋮ menu and choose **Custom repositories**
2. Add `https://github.com/Roving-Ronin/BatteryLedger` as an **Integration**
3. Search for **BatteryLedger** and click **Download**
4. Restart Home Assistant, then go to **Settings → Devices & services → Add integration → BatteryLedger**

### HACS (Home Assistant 2026.10 and older)

[![Open this repository in HACS][hacs-button]][hacs-url]

Or add it manually:

1. Open **HACS**, open the ⋮ menu and choose **Custom repositories**
2. Add `https://github.com/Roving-Ronin/BatteryLedger` as an **Integration**
3. Search for **BatteryLedger** and click **Download**
4. Restart Home Assistant, then go to **Settings → Devices & services → Add integration → BatteryLedger**

## Setup

1. **Find your battery:** search the Store by text, brand, model (e.g. Sigenergy SigenStor vs Neo), region and
   phase (single / three), or enter the details from your datasheet manually. **Tick every model installed**, e.g.
   both BAT 8.0 and BAT 10.0 if you have a mix. The Store list is downloaded once a day (no account needed) and a copy
   ships with each release for offline use.
2. **Battery groups:** for each model, the number of modules/units and the warranty start date. Use *Add another
   model or later install* for modules of the same model added later with a different warranty start date.
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

Home Assistant 2025.1 or newer. BatteryLedger's own icon and logo show from 2026.3 onwards; older versions show a placeholder.

## Sensor attribute notes

The `notes` attribute on the *Throughput used* and *Warranty floor health* sensors lists codes for anything
estimated or substituted:

| Code | Meaning |
|---|---|
| `plant_energy_split_by_capacity_and_age` | Several battery groups share one plant energy counter, so it was split between them by usable capacity × days in service (an estimate) |
| `basis_unstated_using_charged` | The warranty doesn't say whether throughput counts charged or discharged energy, so charged energy (the larger figure) was used |
| `basis_unstated_using_discharged` | As above, but only a discharged energy sensor is configured |
| `discharged_sensor_missing_using_charged` | The warranty counts discharged energy, but no discharged sensor is configured |
| `charged_sensor_missing_using_discharged` | The warranty counts charged energy, but no charged sensor is configured |
| `module_counters_not_used:<spec id>:<found>/<configured>` | Module sensors exist for that battery group but couldn't be used (not every module found, or the warranty isn't per unit on discharged energy) |

## Reporting problems

Use the [issue templates](https://github.com/Roving-Ronin/BatteryLedger/issues/new/choose). Bug reports missing
the BatteryLedger version, Home Assistant version or battery are labelled `question` and closed after 5 days if
they're not updated. Comment `/reopen` on your own closed issue to reopen it.

## Development

```bash
pip install -r requirements_test.txt
pytest -q
```

`tests/test_ledger.py` covers the calculations without Home Assistant; `tests/test_integration.py` runs the setup
flow, sensors and Store-revision repairs in a test Home Assistant instance.

The bundled Store snapshot is `custom_components/battery_ledger/data/index_snapshot.json`; refresh it from the
Store's published `index.json` before each release.

## Releasing

Draft a new GitHub release, create a tag such as `v0.2.0` on `main`, and publish. The release workflow takes the
version from the tag, writes it into `manifest.json`, attaches `battery_ledger.zip` to the release (what the Marketplace / HACS installs
and the download badge counts), and commits the version back to `main`. Mark betas as a pre-release (e.g. `v0.3.0b1`);
they don't change the version on `main`.


<!-- Badges -->

[marketplace-badge]: https://img.shields.io/badge/Marketplace%20-%20Custom-orange?style=flat-square
[release-badge]: https://img.shields.io/github/v/release/Roving-Ronin/BatteryLedger?style=flat-square&color=blue&label=Release
[downloads-badge]: https://img.shields.io/github/downloads/Roving-Ronin/BatteryLedger/total?style=flat-square&label=Downloads
[installs-badge]: https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.battery_ledger.total&style=flat-square
[maintained-badge]: https://img.shields.io/badge/Maintained-yes-brightgreen?style=flat-square
[activity-badge]: https://img.shields.io/github/commit-activity/y/Roving-Ronin/BatteryLedger?style=flat-square&label=Commit%20Activity
[license-badge]: https://img.shields.io/github/license/Roving-Ronin/BatteryLedger?style=flat-square&label=License
[repo-stars-badge]: https://img.shields.io/github/stars/Roving-Ronin/BatteryLedger?style=flat-square&logo=github&label=Repo%20Stars
[validate-badge]: https://img.shields.io/github/actions/workflow/status/Roving-Ronin/BatteryLedger/validate.yaml?branch=main&label=Validate&style=flat-square
[tests-badge]: https://img.shields.io/github/actions/workflow/status/Roving-Ronin/BatteryLedger/tests.yaml?branch=main&label=Tests&style=flat-square

<!-- Install buttons -->

[marketplace-button]: https://my.home-assistant.io/badges/marketplace_repository.svg
[marketplace-url]: https://my.home-assistant.io/redirect/marketplace_repository/?owner=Roving-Ronin&repository=BatteryLedger
[hacs-button]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-url]: https://my.home-assistant.io/redirect/hacs_repository/?owner=Roving-Ronin&repository=BatteryLedger&category=integration

<!-- References -->

[repo-url]: https://github.com/Roving-Ronin/BatteryLedger
[release-url]: https://github.com/Roving-Ronin/BatteryLedger/releases
[installs-url]: https://analytics.home-assistant.io/custom_integrations.json
[commits-url]: https://github.com/Roving-Ronin/BatteryLedger/commits/main
[validate-url]: https://github.com/Roving-Ronin/BatteryLedger/actions/workflows/validate.yaml
[tests-url]: https://github.com/Roving-Ronin/BatteryLedger/actions/workflows/tests.yaml
[license-url]: https://github.com/Roving-Ronin/BatteryLedger/blob/main/LICENSE
