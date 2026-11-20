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

If that button doesn't open BatteryLedger, the HACS button below also works on Home Assistant 2026.11 and newer,
or add it manually:

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

1. **Find your battery:** choose **Detect from my battery's integration**, search the Store, or enter the details
   from your datasheet manually.
   - **Detect** looks through the integrations BatteryLedger knows (step 3) and reads what they report about the
     batteries to suggest the model and number of modules, which you confirm on the next step:
     - **Sigenergy (Sigenergy Local Modbus):** each inverter's battery pack count and rated battery capacity give
       the capacity per module (48.36 kWh ÷ 6 = 8.06 kWh: BAT 8.0), and its model type tells SigenStor from Neo.
     - **sigenergy2mqtt (Sigen Cloud):** each module's rated capacity, and with more than one inverter each
       inverter's rated battery capacity (the Cloud modules don't say which inverter they're on).
     - **Huawei / iStore (wlcrs):** rated capacity ÷ battery packs with a serial number, counted per tower: 5.0 kWh
       is the S0, 6.9 kWh the S1. The S1 is shown as detected (the Huawei and iStore warranties are the same); for the S0 you choose
       Huawei or iStore, as their warranties differ.
     - **BYD Battery Box:** towers × modules and capacity per module (HVS or HVM).
     - **AlphaESS (senalse):** battery module count.
     - **Energy Manager and other integrations:** rated capacity alone, as a whole number of modules of one model
       (Energy Manager's inverter brand narrows the brand). When more than one model fits, you choose.
     - **Energy dashboard battery:** a battery set up in Home Assistant's Energy dashboard (Settings → Dashboards →
       Energy) whose sensors no sensor profile found, e.g. from an integration the Store doesn't know yet. Its
       energy in and out sensors are used as charged and discharged energy; you search the Store for the model.

     With batteries on more than one tower or inverter (e.g. a Huawei inverter with a second tower added later),
     Detect lists each one (inverter, inverter model, tower, modules) and asks whether they were installed together.
     Choose **Installed separately** for one battery group per tower, each with its own model (e.g. Huawei
     LUNA2000-5-S0 for the first tower, iStore IS-BATT-5000-ES for a later one), warranty start date and cost.

     Some of these sensors are off by default in their integration. Detect lists them and, if you agree, turns them
     on, checks for their readings after 45 seconds (and again 45 seconds later if needed), then carries on; it
     never turns on a sensor you turned off. Sensors it turns on stay on, even if you remove BatteryLedger later;
     turn them off under Settings → Entities if you no longer want them.
   - **Store search:** by text, brand, region and phase (single / three), then pick the model (e.g. Sigenergy
     SigenStor vs Neo, Sungrow SBR vs SBH) from those matching. **Tick every model installed**, e.g. both BAT 8.0
     and BAT 10.0 if you have a mix.

   The Store list is downloaded once a day (no account needed) and a copy ships with each release for offline use.
2. **Battery groups:** for each model, the number of modules/units, the warranty start date and what they cost
   (optional, in your Home Assistant currency). Use *Add another model or later install* for modules of the same
   model added later with a different warranty start date: they keep their own cost and warranty clock.
3. **Inverter integration:** BatteryLedger looks for your inverter integration's sensors using the Store's
   *sensor profiles* (matched by entity registry unique ID, so renamed entities still work) and lists the
   integrations it knows for your battery brand:
   - **Sigenergy:** [TypQxQ's Sigenergy Local Modbus](https://github.com/TypQxQ/Sigenergy-Local-Modbus),
     [sigenergy2mqtt](https://github.com/seud0nym/sigenergy2mqtt)
   - **AlphaESS:** [senalse's AlphaESS Modbus TCP](https://github.com/senalse/ha-alphaess-modbus)
   - **BYD:** [redpomodoro's BYD Battery Box](https://github.com/redpomodoro/byd_battery_box) (reads the battery's
     BMS, including state of health), or [redpomodoro's Fronius Modbus](https://github.com/redpomodoro/fronius_modbus)
     with a Fronius GEN24
   - **Deye:** [davidrapan's Solarman](https://github.com/davidrapan/ha-solarman),
     [Lewa-Reka's ESPHome Deye Inverter](https://github.com/Lewa-Reka/esphome-deye-inverter)
   - **Fronius (GEN24 with Reserva or BYD):** [redpomodoro's Fronius Modbus](https://github.com/redpomodoro/fronius_modbus).
     The core Fronius integration has no battery energy totals.
   - **GoodWe (ET, EH, BT and BH hybrids):** [GoodWe](https://www.home-assistant.io/integrations/goodwe/) (core, or
     [mletenay's custom version](https://github.com/mletenay/home-assistant-goodwe-inverter)). GoodWe's ES-family
     inverters don't report lifetime battery energy, so use Energy Manager or choose the sensors yourself.
   - **Huawei and iStore:** [wlcrs's Huawei Solar](https://github.com/wlcrs/huawei_solar). With an EMMA (or
     SmartLogger), its site-wide totals cover a cascaded stack of up to 3 inverters.
   - **Sungrow:** [mkaiser's Sungrow SHx Modbus package](https://github.com/mkaiser/Sungrow-SHx-Inverter-Modbus-Home-Assistant),
     [Wingman3434's Sungrow SHx Inverter](https://github.com/Wingman3434/sungrow-shx-inverter-hacs)
   - **All of these brands:** [Energy Manager](https://github.com/ha-energymanager/ha-energymanager). If it's
     installed, its battery install date and cost pre-fill the first battery group, and the install date and cost
     of batteries added later (`battery_install_date_2`, `battery_install_cost_2`) the second.

   You can also choose the sensors yourself.
4. **Battery modules** (when available, e.g. sigenergy2mqtt with the Sigen Cloud API enabled): per-module
   discharge counters are assigned to your battery groups by each module's rated capacity, and each module is
   tracked against its own warranty limit.
5. **System:** whether cost per
   kWh and cost sensors show the currency symbol (`$`, `$/kWh`, the default) or code
   (`AUD`, `AUD/kWh`, which Home Assistant formats as money in each user's locale), and the sensors (filled in from step 3 if detected): lifetime
   **charged** and/or **discharged** energy, and optionally rated capacity (hardware check), battery **state of
   charge** (for [measured capacity](#measured-usable-capacity-and-soh)), battery state of health, and **battery
   pack state of health** sensors (each pack's own SoH, e.g. Solarman on a three-phase Deye; with no whole-battery
   SoH sensor, their average is used).

Later, under **Configure**:
- **Sensors and currency:** the source sensors and the currency display.
- **Battery groups:** correct a group's number of units or warranty start date, remove a group (with its cost
  and battery modules), or add batteries installed later, such as a second stack. The added group's warranty
  start and cost are filled in from Energy Manager's `input_datetime.battery_install_date_2` and
  `input_number.battery_install_cost_2` when you use them. See [Battery groups](#battery-groups).
- **Battery towers:** each tower's state of charge and energy sensors and its battery group, for measuring each
  tower (see [Measured usable capacity and SoH](#measured-usable-capacity-and-soh)). 0 removes them.
- **Battery costs:** what each battery group cost.
- **Service life and export cost:** Estimated Service Life and the export cost basis (also as the
  `number.battery_ledger_estimated_service_life` and `select.battery_ledger_export_cost_basis` entities).
- **Update the Store list now:** download the latest Store list straight away (otherwise once a day). If a
  battery you use has been revised, Settings → Repairs offers the change for you to review.
- **Export setup:** download a setup file to keep (see [Moving to a new server](#moving-to-a-new-server)).

**Reconfigure** (the setup's ⋮ menu under Settings → Devices & services → BatteryLedger) downloads the latest
Store list, then runs the whole setup again: Detect, Store search or manual entry, then the sensors. The battery
models you choose come from that list, so they include any Store revisions (no Repairs review needed). Each battery group's warranty start date and cost,
the sensors and the setup's name are filled in from the current setup. The last step replaces the setup;
Estimated Service Life, Export Cost Basis, the card settings, the entities and the measured capacity (with the same
state of charge sensor) are kept. Close the window part way through to leave the setup as it was.

Changes recalculate every sensor. Costs use your Home Assistant currency (Settings → System → General).

### Moving to a new server

A Home Assistant backup includes BatteryLedger: restore it on the new server and nothing else is needed.
BatteryLedger keeps no history of its own; throughput, warranty used and costs are worked out from your
inverter's lifetime counters, so they carry on once its integration is running.

To set up again without restoring a backup, save a **setup file** on the old server: **Configure → Export
setup** → **Download**. On the new server, add BatteryLedger, choose **Import a saved setup** and choose the file. It holds the battery groups (with their copied specs),
warranty start dates and costs, the sensors chosen, which battery module (by serial number) is in which group,
the name, currency style and card settings. On import, the saved sensors are used where they exist on the new
server (otherwise Detect's), and modules keep their battery group by serial number, so two groups of the same
model are restored correctly.

The file includes serial numbers and costs: keep it private. To share details for help, use Download
diagnostics instead (see [Reporting problems](#reporting-problems)).

### Battery groups

A battery group is batteries of one model with the same warranty start date and cost. It isn't a stack: one
stack can hold several groups, and one group can't have more units than the model allows.

| Example system | Battery groups |
|---|---|
| One Sigen stack of 4 × BAT 8.0 | 4 × BAT 8.0, install date |
| 2 × BAT 8.0 added to that stack later | + 2 × BAT 8.0, the date they were added, their cost |
| A second stack of 6 × BAT 10.0 | + 6 × BAT 10.0, its date, its cost |
| Two full stacks of 6 × BAT 8.0 installed together | 6 × BAT 8.0 and 6 × BAT 8.0, same date, cost split between them |

- **Unit limits** come from the Store spec and apply to each group (Sigen: 1–6 modules per energy controller).
- **Warranty limits** are worked out per group from its units (per unit × units, a per-system figure, or the
  warranty's table row for that many units), and each group's warranty time runs from its own start date.
- **Warranty start:** use the date the manufacturer's warranty counts from for those batteries. That's usually
  the date they were installed or commissioned, but check whether added modules carry the original stack's
  warranty date instead.
- **Shared counters:** with one plant-level counter, energy is split between groups by usable capacity × days in
  service (see [What the numbers mean](#what-the-numbers-mean-and-dont)).
- **Per-module tracking:** when you add a group, or add units to one, under Configure → Battery groups, any module
  sensors your integration now reports that aren't tracked yet are offered for that group (matched by rated
  capacity). A group is tracked per module only when every one of its modules is found; otherwise it uses the
  plant counter.
- Groups can be changed, removed or added later under Configure → Battery groups.

**Dates:** the warranty start date picker and the card show dates in the format set in each user's Home Assistant profile
(your name at the bottom of the sidebar → Profile → **Date format**). It defaults to your profile language's
format, so English shows month-day-year; choose **Day-Month-Year** there for day first (e.g. 18/7/2035).

## Dashboard card

<p align="center"><img src="images/card.png" alt="BatteryLedger card for a SigenStor BAT 8.0 × 6 battery" width="451"></p>

BatteryLedger installs its own dashboard card; there's nothing extra to download or add as a resource. Edit a
dashboard, add a card and pick **BatteryLedger**, then choose the setup if you have more than one. In YAML:

```yaml
type: custom:battery-ledger-card
entry_id: <optional; the first setup is used if left out>
```

With more than one battery group, a **Battery group** switcher under the title shows **All** (the whole setup)
or one group (1, 2, 3 …). A group shows its own status, warranty rings, end dates, EoSL, remaining warrantied usage
and warranty curve (against the battery's reported state of health); cost stays for the whole setup.

The card has four sections:
- **Warranty:** two rings show how much of the warranty is used by age (time elapsed) and by usage (throughput).
  The larger one is the warranty driver, shown first with cycles per day. Below are two warranty end dates, each
  above its share: by age, labelled with your battery's warranty period (e.g. **Warranty Ends (10 years)**:
  warranty start + 10 years), and **Warranty Ends (by usage)**, when the throughput limit would be reached at your
  average daily use so far. The warranty ends at whichever comes first, shown in red. Then **Estimated Service
  Life (ESL)**, which admins can change in its box, **End of Service Life (EoSL)** and **Estimated usage at
  EoSL** (with its share of the warranted throughput).
- **Throughput:** remaining warrantied usage (rated throughput) counts down, with a marker for what's projected
  to be left when the warranty ends.
- **Cost:** value used to date (the `cost_consumed_to_date` sensor), remaining value, cost per kWh (by usage and
  by age), and **Export Cost** with its basis; admins choose the **Export Cost Basis** there.
- **Health:** your battery's reported state of health against the warranty curve (Estimated Usable
  Capacity, what the warranty allows at this age and usage), on a scale from the end-of-warranty capacity
  to 100%. A battery that reports no SoH shows the measured SoH instead (**Actual SoH (measured)**), and
  while that's still being measured, how many charges and discharges it has so far; where the battery does report SoH, the measured figure
  is shown under it as a cross-check. The hardware capacity check and module figures are shown when available.

Tap any figure to open its sensor. The bottom right corner shows the BatteryLedger version; admins also see a cog just to its left. It opens the card
settings: decimal places for cost per kWh (2 to 5), how dates are shown (your Home Assistant date format, or
day month year such as 18 Jul 2035), and which sections to show. The settings are saved for each
BatteryLedger setup, so the card looks the same on every dashboard and device.

## Sensors

Entity IDs are `sensor.battery_ledger_<name>`. A second BatteryLedger setup gets `_2` on the end, and so on.

At startup the sensors stay unavailable until every source sensor you chose has reported, so a battery
integration that's still connecting (Modbus, MQTT, cloud) isn't mistaken for a sensor that isn't set up. If one
hasn't reported 5 minutes after Home Assistant starts, BatteryLedger calculates without it (with the usual note).
If a source drops out later, its last reading is used until it's back.

| Entity ID (`sensor.battery_ledger_…`) | What it shows | Attributes |
|---|---|---|
| `total_rated_throughput` | Total warranted energy throughput for the configured units | `total_pack_count` |
| `remaining_rated_throughput` | Warranted throughput still left | |
| `rated_throughput_used` | Energy counted against the warranty so far | `groups`, `notes` |
| `cycles_per_day` | Full equivalent cycles per day: energy counted ÷ days since warranty start ÷ rated capacity (the inverter's rated capacity sensor, else the spec's figure × units) | |
| `warranty_time_elapsed` | Time since warranty start as % of the warranty period | |
| `projected_warranted_throughput` | Throughput by the end of the warranty at the average rate so far (capped at the limit) | `average_daily_kwh`, `low_confidence` |
| `cost_per_kwh_rated` | Battery cost ÷ warranted throughput (battery groups with a cost) | |
| `cost_per_kwh_projected` | Battery cost ÷ projected throughput (battery groups with a cost) | |
| `cost_per_kwh_export` | Battery cost per kWh for a home energy manager, on the basis chosen with Export Cost Basis (see [Battery cost for exports](#battery-cost-for-exports)) | `basis`, `age`, `usage`, `esl`, `soh_trend`, `soh_trend_years`, `driver`, `low_confidence` |
| `estimated_usage_at_eosl` | Estimated usage at EoSL: throughput at the average rate so far until each battery group's End of Service Life, not capped at the warranted throughput | `warranted_throughput_kwh`, `percent_of_warranted`, `estimated_service_life_years`, `low_confidence` |
| `end_of_service_life` | Earliest End of Service Life: a battery group's warranty start + Estimated Service Life (see [ESL and EoSL](#estimated-service-life-esl-and-end-of-service-life-eosl)) | `estimated_service_life_years`, `groups` |
| `cost_consumed_to_date` | Cost apportioned to warranty life used: each battery group's cost by its own warranty driver (time elapsed or throughput used, whichever is further along), added up. `percent_of_rated_life_used` stays the throughput share. Each group's `cost` and `cost_consumed` are in the `groups` attribute | `percent_of_rated_life_used`, `estimated_remaining_value` |
| `initial_usable_capacity` | Usable capacity at beginning of life | |
| `estimated_usable_capacity` | Warranty floor health %: the minimum capacity the warranty guarantees today (see below) | `remaining_usable_kwh`, `degradation_driver`, `warranty_status`, `groups`, `notes` |
| `hardware_capacity_validation` | Whether the inverter's reported capacity matches the configured units (if a rated capacity sensor is set) | `configured_rated_kwh`, `reported_hardware_kwh` |
| `soh_above_warranty_floor` | Reported state of health minus the warranty floor, in percentage points (if a SoH sensor is set) | `reported_soh_pct`, `warranty_floor_pct` |
| `most_used_module_throughput` | Highest per-module share of its warranted throughput (module tracking) | `worst_module`, `modules`, `module_total_vs_plant_pct` |
| `module_soc_spread` | Highest minus lowest module state of charge right now (module tracking) | `module_soc` |
| `measured_usable_capacity` | Usable capacity measured from charge and discharge runs (if a state of charge sensor is set; see below) | `status`, `charge_runs`, `discharge_runs`, `round_trip_efficiency_pct`, `initial_usable_kwh` |
| `measured_soh` | Measured usable capacity ÷ usable capacity when new (if a state of charge sensor is set) | `status`, `reported_soh_pct`, `warranty_floor_pct` |

*Projected Warranted Throughput* is average daily throughput × warranty days, with the days counted from the
warranty start date, capped at the warranted total. Friendly names start with "Battery" for every brand.

### Battery cost for exports

`sensor.battery_ledger_cost_per_kwh_export` is the battery's cost per kWh to use as the battery cost, or the
minimum sell price for battery exports, in a home energy manager (EMHASS, HAEO, Energy Manager). Add your margin
there.

Its attributes give the cost per kWh on each basis, and `basis` says which one is the state:

| Attribute | Cost per kWh |
|---|---|
| `age` | Battery cost ÷ throughput projected by the warranty end date, at the average rate so far |
| `usage` | Battery cost ÷ warranted throughput (Cost Per kWh (Rated)) |
| `esl` | Battery cost ÷ throughput projected to the End of Service Life (see below) |
| `soh_trend` | Battery cost ÷ throughput projected until the SoH trend reaches the warranty capacity (`soh_trend_years`), once there's enough SoH history |

What the state is follows **Export Cost Basis** (`select.battery_ledger_export_cost_basis`, or Configure →
Service life and export cost):

- **Warranty (whichever ends first)** (default): the higher of `age` and `usage` (`driver` says which). The
  conservative choice.
- **Warranty by age** / **Warranty by usage:** always `age`, or always `usage`, regardless of which limit ends the warranty
  first.
- **Estimated Service Life (ESL):** `esl`.
- **Cheapest:** the lowest of the warranty figure, `esl` and `soh_trend`. The warranty limit that doesn't end the
  warranty isn't a candidate: its throughput isn't reached within the warranty.

For the first 30 days, and until there's any usage to project from, it's `usage` whatever the setting
(`low_confidence: true`): an early projection can be far too high and would stop battery exports. With a warranty
that has no throughput limit, the warranty figure is `age`. Figures are per kWh discharged (charging losses are for
your energy manager to allow for), and battery groups without a cost aren't included.

### Estimated Service Life (ESL) and End of Service Life (EoSL)

**Estimated Service Life** (`number.battery_ledger_estimated_service_life`, or Configure → Service life and export
cost) is how many years you expect to keep the batteries: one value per setup, counted from each battery group's
warranty start. Until you set it, it's **15 years** (or the warranty period, if a battery's is longer). With 15
years, a stack from 2020 reaches its **End of Service Life** in 2035 and one added in 2025 in 2040. `sensor.battery_ledger_end_of_service_life` is the earliest;
each group's is in its `groups` attribute. `sensor.battery_ledger_estimated_usage_at_eosl` is the throughput
expected by then, at the average rate so far, and its share of the warranted throughput (over 100% once use runs
past the warranty's limit). Changing ESL or the export cost basis recalculates straight away, so
both can be set from a dashboard or an automation.

### Measured usable capacity and SoH

Many batteries don't report a state of health, or report one that barely moves. With a **state of charge** sensor
(Configure → Sensors and currency; detected for every integration the Store knows) BatteryLedger measures what the
battery really holds, using the method from [Energy Pilot](https://github.com/Clahen86/Energy-pilot) (MIT):

- Each run of charging or discharging in which the state of charge moves at least 10 points is recorded as kWh
  per point, from the lifetime charged and discharged counters (what went in minus anything that came out
  meanwhile, and the other way round). Small wobbles and runs that don't add up (a counter reset, a jump in the
  state of charge) are ignored.
- Charging takes more energy per point than discharging gives back, because of losses. The geometric mean of the
  two medians (the last 20 runs each way) cancels the losses out: that's the **measured usable capacity**, and
  their ratio the **round-trip efficiency**. The medians smooth out the BMS's state-of-charge drift and
  recalibration jumps.
- It needs 3 runs each way (`status`: `insufficient` until then; the card shows **Measuring capacity:** with how
  many charges and discharges it has so far). With only one energy counter it measures that way alone
  (`one_direction`), and the losses aren't cancelled; the other direction's runs attribute is empty.
- **Measured SoH** is the measured usable capacity ÷ the usable capacity when new (`initial_usable_capacity`).

**Battery towers.** Where each tower (stack) reports its own state of charge and lifetime energy, BatteryLedger
measures each tower instead of the whole battery: each battery unit on a Huawei inverter (2 per inverter, wlcrs),
each Sigenergy inverter's battery (Sigenergy Local Modbus, sigenergy2mqtt) and each BYD tower (BYD Battery Box, up
to 3 on HVS / HVM). Detect finds them and setup shows a **Battery towers** step (how many, then each tower's
sensors and battery group); Configure → Battery towers changes them for any setup. The whole battery's measured
capacity is the towers' added up, and each battery group gets its own measured SoH (its towers' capacity ÷ the
group's usable capacity when new), in Measured SoH's `groups` attribute and on the card when you pick a group.
Measured Usable Capacity's `towers` attribute has each tower's capacity, SoH (against its share of the group, the
group's towers taken as equal in size), efficiency, runs and status; the card's run counts are the slowest tower's.
With towers, the whole battery's state of charge sensor isn't used for measuring. GoodWe's and Deye's second
battery report SoC and power but no energy of their own, so they're measured as one battery.

The runs are kept across restarts and start again if you choose a different state of charge sensor (per tower:
a different tower SoC sensor). Like the BMS's
own SoH, it's an estimate: it's only as good as the state of charge reading, which is least accurate in the middle
of the range and right after the BMS recalibrates.

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
| `energy_counters_zero` | The energy counters read 0 on a battery in service for 30 days or more. Usually the source isn't reporting (e.g. an integration publishing 0): check the charged / discharged sensors under Configure |

An SoH reading of 0% is treated as no reading (some integrations publish 0 when the battery doesn't report SoH),
so SoH Above Warranty Floor is unavailable instead of far below the floor.
The card's Actual SoH tile then says why there's no figure: not set up yet, not available from your integration
for your battery (from the Store's sensor profile), or no reading from the sensor that's chosen.

`degradation_driver` (on *Warranty floor health*) is `Age (Time Elapsed)` or `Throughput (Cycles)`: whichever of
time and throughput is further through the warranty. Before 0.1.9 the second was `Throughput (Cycle Abuse)`.

## Reporting problems

Questions, ideas and setup help go in [Discussions](https://github.com/Roving-Ronin/BatteryLedger/discussions).
For a bug or a feature request, use the
[issue templates](https://github.com/Roving-Ronin/BatteryLedger/issues/new/choose). Bug reports missing the
BatteryLedger version, Home Assistant version or battery are labelled `question` and closed after 5 days if they're
not updated. Comment `/reopen` on your own closed issue to reopen it.

To help with a problem, attach BatteryLedger's diagnostics: Settings → Devices & services → BatteryLedger → ⋮ →
**Download diagnostics**. It holds the setup, the source sensors' current readings and the latest calculation,
with module serial numbers replaced by M1, M2… and costs removed. Check it before attaching.

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
[marketplace-url]: https://my.home-assistant.io/redirect/marketplace_repository/?owner=Roving-Ronin&repository=BatteryLedger&category=integration
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
