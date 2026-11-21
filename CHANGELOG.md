# Changelog

Every release opens with a **TL;DR**: a handful of short bullets, rewritten as a whole
whenever an entry is added. Entries are direct: symptom, cause, fix, with the issue link and
credit where there is one.

## v0.4.1 (2026-11-21)

### TL;DR
- After a restart, savings no longer show "Home Energy Advisor isn't available" for up to 15 minutes
- Fixed a setup error just after midnight while savings are still small

### Fixed
- Whole installation, after a restart: BatteryLedger now waits for Home Assistant to finish starting before asking
  Home Energy Advisor, and while HEA doesn't answer it asks again every 30 seconds (for up to 30 minutes, then with
  the 15-minute ask), instead of waiting for the next 15-minute ask. The past days follow as soon as it answers.
- Return on investment: with only a few cents saved so far (e.g. just after midnight on the first day), the
  break-even date could be millions of days away, which overflowed and stopped the setup loading. A break-even more
  than 100 years away now has no date.

## v0.4.0 (2026-11-21)

### TL;DR
- **Return on investment**: savings to date, how much of the battery is paid back, the break-even date and
  projected lifetime savings, from Home Energy Advisor's plan comparison (whole installation) or a battery savings
  sensor (battery only). Set up in Configure → ROI; a Repairs notice asks each setup to choose
- Card: a new **Return on Investment** section, and Financials redone as two tiles: **Battery value** (left of the
  cost, with a bar for what's used) and **Cost per kWh** (by usage, by age and export, with the export basis beside
  it)
- Brings together 0.4.0b1, b2 and b3 (below)

### Changed (since 0.4.0b3)
- Card, Return on Investment:
  - **Paid back** replaces "ROI to date" and Break even: savings as a share of the investment with a bar, the
    break-even date and time to go, and where ROI ends up at End of Service Life ("+155% by EoSL", from
    `roi_at_eosl`; a chosen battery group's own).
  - **Savings to date**: shows the prior savings it includes, and the daily rate with a year's worth
    ("$5.28 a day · $1,926 a year", moved from Projected lifetime savings). This week, This month and This year show
    only once they differ from the shorter period (on the first days they're all the same).
  - **Projected lifetime savings**: the figure at EoSL as the headline, then by warranty end.
- Card, Financials: **Battery value** (remaining value, a bar for the value used, and the battery cost) replaces
  Value used to date and Remaining Value; **Cost per kWh** now includes the export cost, labelled with its basis
  ("export (ESL)"), and the Export Cost Basis dropdown is a small one beside the tile's label.
- Card: amounts from 1,000 up are shown without cents ($10,274); smaller amounts and per-kWh costs keep them.
  The sensors are unchanged.

## v0.4.0b3 (2026-11-21)

### TL;DR
- **Beta.** The card says in words how many days Home Energy Advisor couldn't price, instead of showing
  `current_plan_not_priced`

### Fixed
- Card, ROI: the `current_plan_not_priced` status (new in 0.4.0b2) showed as the raw code. It now reads
  "330 days left out: Home Energy Advisor couldn't price them." (from the savings sensor's `days_not_priced`).
  A test now checks that every status the savings sensor can report has wording on the card.

## v0.4.0b2 (2026-11-21)

### TL;DR
- **Beta.** A Repairs notice asks each setup to choose how to work out return on investment, so nobody misses it
- Off is remembered as a choice
- Fixed: past days' savings weren't filled in when Home Energy Advisor loaded after BatteryLedger; days HEA can't
  price are now shown on the savings sensor's `status`

### Added
- Settings → Repairs: **"BatteryLedger: choose how to work out return on investment"** for any setup without an
  ROI choice (every setup from before 0.4.0, and new ones). It explains what ROI gives and what it needs, and
  **Fix** opens the same form as Configure → ROI (Whole installation, Battery only or Off). Any choice ends it.

### Changed
- Card settings, Display Sections: **Return on Investment** (was "ROI"), the same as the section's heading.
- Card, Break even: the time to go is shown in years, months and days from today to the date ("in 4 years,
  3 months & 11 days"), not as a number of days. The `break_even_date` sensor's `days_to_go` stays in days.
- Configure → ROI → **Off** is kept as a choice (`roi: {mode: off}`) instead of removing the settings, so the
  notice doesn't come back. The ROI sensors are still only created when ROI is on.

### Fixed
- Whole installation: if Home Energy Advisor wasn't loaded yet when BatteryLedger started (after a restart),
  the past days were dropped until the next restart, so This week, This month and This year all showed the same
  as Today. They're now kept and asked for as soon as HEA answers (within 15 minutes).
- Whole installation: days Home Energy Advisor can't price its current plan for (its price sensors had no
  statistics then, e.g. no `state_class`) were left out silently with `status: ok`. They're still left out (not
  $0), but `status` is now `current_plan_not_priced` and a new `days_not_priced` attribute says how many.

## v0.4.0b1 (2026-11-21)

### TL;DR
- **Beta**, for testing with real Home Energy Advisor data; the card's ROI section may change before 0.4.0
- **Return on investment**: savings to date, ROI, break-even date and projected lifetime savings, from Home Energy
  Advisor's plan comparison (whole installation) or a battery savings sensor (battery only)
- Card: a new **Return on Investment** section between Financials and Health

### Added
- Configure → **ROI (return on investment)**: **Whole installation** (Home Energy Advisor 1.7 or later: each day,
  the chosen plan without solar or battery's cost of everything the house used, all from the grid, less what the
  current plan actually cost, from its `compare_plans` action), **Battery only** (a running-total savings sensor,
  Home Energy Advisor's Battery Savings found and filled in) or **Off**; savings before these figures, other system
  costs (whole installation) and the date savings count from.
- Savings kept per day: days since install asked for in the background (newest first), the last 35 days redone
  nightly and today every 15 minutes, each finished month checked every Monday against its days and redone if it differs,
  everything redone when the chosen plan changes. Days with no recorded data aren't counted as $0. Kept in
  storage (`battery_ledger.savings.<entry>`), removed with the setup.
- Sensors (only with ROI set up): `savings_to_date` (today, this week, this month, this year, days counted,
  status...), `return_on_investment` (%, with investment, net position, ROI at warranty end and at EoSL),
  `break_even_date` (days to go, daily rate, confidence) and `projected_lifetime_savings` (at warranty end, at
  EoSL, per year). Projections run to the last battery group's warranty end and End of Service Life; confidence is
  low with less than a year of savings.
- Card: **Return on Investment** section (Display Sections: ROI), between Financials and Health with a divider
  either side: savings to date with today / week / month / year, ROI to date with the net position, break-even
  date, projected lifetime savings with its End of Service Life date, and why figures aren't
  coming if they aren't. With a battery group picked in the switcher, the projections run to that group's own
  warranty end and End of Service Life (All: the last group's); `projected_lifetime_savings` has them per group in
  its `groups` attribute. Savings and the investment stay the whole installation's.

### Changed
- Card: the Financials section has a heading, like Return on Investment and Health.
- Card: a negative amount shows its sign before the currency (-$24,641.45, not $-24,641.45).
- Config entry version 1.8 (no change to stored data; ROI settings are an optional new field).

## v0.3.4 (2026-11-21)

### TL;DR
- Card: Financials follow the battery group switcher, so each group shows its own value used, remaining value,
  cost per kWh and export cost

### Added
- Each battery group's own financials, worked out the same way as the setup's but for that group's cost alone:
  `remaining_value`, `cost_per_kwh_rated` (by usage), `cost_per_kwh_projected` (by age), `cost_per_kwh_export`
  and its `export_basis`, in each group of the `groups` attribute (Rated Throughput Used). The export cost follows
  the setup's Export Cost Basis setting. A group without a cost has none.
- Card: picking a group in the switcher shows that group's Financials; All shows the whole setup's, as before.

## v0.3.3 (2026-11-20)

### TL;DR
- Card: the Financials tiles are always 2 × 2 (Export Cost no longer sits on a row of its own on a wider card)

### Fixed
- Card, Financials: on a card wide enough for three tiles in a row, Export Cost wrapped onto a row by itself.
  The four tiles are now always two by two: Value used to date and Remaining Value, then Cost per kWh and
  Export Cost.

## v0.3.2 (2026-11-20)

### TL;DR
- Card: thin lines between the warranty figures and Remaining Warrantied Usage, and between Financials and Health
- Card settings: **Cost** is now **Financials**, **Throughput** is now **Usage & Throughput**

### Changed
- Card: a thin grey line between the warranty figures and Remaining Warrantied Usage, and another between the
  Financials tiles and Health, each only when both sections are shown. The gap already there is split either side
  of the line, so the card is only the two lines (2 px) taller.
- Card settings, Display Sections: **Cost** is now **Financials** (value used, remaining value, cost per kWh and
  export cost) and **Throughput** is now **Usage & Throughput**. Their saved names follow (`cost` → `financials`,
  `throughput` → `usage`): card settings saved before, or in a setup file exported before, keep their choices
  under the new names, and a card still cached in a browser can still save with the old ones.

## v0.3.1 (2026-11-20)

### TL;DR
- Configure → **Battery towers** finds the towers on setups made before 0.3.0 (it showed 0)
- The towers step lists each tower with its battery group, and its sensors as bullets

### Fixed
- Configure → Battery towers showed **0** on a setup from before 0.3.0, because it only filled in towers already
  saved. With none saved it now looks for them through the setup's integration, as setup does, and fills in
  tower n as battery group n when there's a group per tower (e.g. two Huawei stacks on one inverter, a group
  each). Reconfigure is no longer needed for this.

### Changed
- Battery towers step: the towers found are a numbered list, each with the battery group it's filled in for,
  and its sensors as bullets underneath.

## v0.3.0 (2026-11-20)

### TL;DR
- **Battery towers**: each tower (stack) measured from its own SoC and energy, so each battery group gets its own
  measured SoH (Huawei, Sigenergy, BYD)
- **Battery pack SoH**: the average of each pack's SoH where there's no whole-battery SoH (Solarman on three-phase
  Deye)
- The SoH sensor's help text is corrected for Deye

### Added
- **Battery towers.** Detect finds towers with their own state of charge and lifetime energy (Store roles
  `tower_soc`, `tower_charged_energy`, `tower_discharged_energy`): each battery unit on each Huawei inverter
  (wlcrs, 2 per inverter), each Sigenergy inverter's battery (Sigenergy Local Modbus, sigenergy2mqtt) and each BYD
  tower (up to 3). Setup shows a **Battery towers** step (how many, then each tower's sensors and battery group;
  with a group per tower, tower n is filled in as group n), as does Reconfigure when the setup has towers;
  Configure → **Battery towers** changes them for any setup (no fixed number; 0 removes them). Each tower is
  measured on its own; Measured Usable Capacity is their sum, with a `towers` attribute (each tower's capacity,
  SoH, efficiency, runs, status, group), and Measured SoH gains a `groups` attribute with each group's measured SoH
  (also `measured_usable_kwh` / `measured_soh_pct` in each group of the `groups` attributes). With towers, the
  whole battery's SoC sensor isn't used for measuring. A tower's runs are kept by its SoC sensor.
- Card: picking a battery group shows that group's measured SoH (and usable kWh against that group's capacity
  when new) when towers are measured.
- **Battery pack state of health sensors (optional)** on the sensors form: each pack's own SoH (Store role
  `pack_soh`; Solarman on three-phase Deye P3 inverters, up to 20 packs). With no battery state of health sensor,
  their average (packs reporting 0 or nothing left out) is the reported SoH, so SoH Above Warranty Floor and the
  card's Actual SoH (battery) work for these batteries.
- Setup files (Export / Import setup) and diagnostics include the towers and pack SoH sensors.

### Changed
- The battery state of health sensor's help text: Solarman on three-phase Deye inverters gives each pack's SoH
  (it said the Deye integrations had none). Solarman's own "Battery SOH", an estimate from total charge, isn't
  used.
- Config entry version 1.7 (no change to stored data; towers and pack SoH sensors are optional new fields).

## v0.2.1 (2026-11-20)

### TL;DR
- **Reconfigure** in the setup's ⋮ menu: the latest Store list, then the whole setup again, with dates, costs,
  sensors and name filled in
- **Update the Store list now** in Configure (it was only in Add service)
- Sensors form: state of charge before state of health, which now says who doesn't report SoH

### Added
- **Reconfigure** (Settings → Devices & services → BatteryLedger → ⋮): downloads the latest Store list (or keeps
  the one it has if the Store can't be reached), then runs the setup steps again (Detect, Store search or manual,
  then sensors). Each battery group's warranty start date and cost (and units, for the same model), the current
  sensors (detected ones take their place) and the setup's name are filled in. Battery models chosen there are
  the Store's latest, revisions included. The last step replaces the setup's battery groups, modules and sensors,
  and the sensor and currency overrides from Configure; Estimated Service Life and Export Cost Basis are kept, as
  are the entities, card settings and measured capacity (if the state of charge sensor is the same).
- Configure → **Update the Store list now**: downloads the Store list straight away. A revised spec in use raises
  its Repairs notice at once instead of at the next daily check.

### Changed
- Sensors form (setup, Reconfigure and Configure): **Battery state of charge sensor** comes before **Battery state
  of health sensor**, whose help text now says who doesn't report SoH (Huawei and iStore batteries, the Deye
  integrations and Fronius Modbus) and which integrations do for those brands.

## v0.2.0 (2026-11-20)

### TL;DR
- **Measured usable capacity and SoH**: what the battery really holds, measured from charge and discharge runs
  against its state of charge (method from Energy Pilot)
- Card: batteries that report no SoH show the **measured SoH** in Health
- **Energy dashboard fallback** in Detect: a battery set up in the Energy dashboard can be used when no sensor
  profile finds its integration
- New optional **battery state of charge** sensor, detected for every integration the Store knows
- Card: tighter line spacing; new setups are named "<Brand> Battery Ledger"

### Added
- Setup / Configure → Sensors and currency: **Battery state of charge sensor (optional)**. Detect fills it in from
  the Store's sensor profiles, which gain a `soc` role for all 12 integrations (plant level, or per inverter where
  the integration has no plant figure).
- `sensor.battery_ledger_measured_usable_capacity` (Measured Usable Capacity) and
  `sensor.battery_ledger_measured_soh` (Measured SoH), only with a state of charge sensor. Runs of charging and
  discharging that move the state of charge at least 10 points are recorded as kWh per point from the lifetime
  energy counters; the geometric mean of the medians (last 20 runs each way) is the usable capacity, with the
  losses cancelled, and their ratio the round-trip efficiency. Needs 3 runs each way (with only one energy
  counter, 3 runs that way, giving a one-way figure with the losses counted in): until then the sensors are
  unknown with `status: insufficient`. Attributes: `status`, `charge_runs`, `discharge_runs`,
  `round_trip_efficiency_pct`, `initial_usable_kwh`; Measured SoH: `status`, `reported_soh_pct`,
  `warranty_floor_pct`. The runs are kept in Home Assistant's storage (`battery_ledger.capacity.<entry>`), start
  again when the state of charge sensor changes, and are removed with the setup. Method credit:
  [Energy Pilot](https://github.com/Clahen86/Energy-pilot) (MIT).
- Card, Health: without a reported SoH, **Actual SoH (measured)** shows the measured SoH (with the above/below
  warranty chip and bar). While it's being measured, that tile shows "Measuring capacity:" with a bullet for each
  direction not yet done ("2 of 3 Charges", "1 of 3 Discharges") in place of the no-SoH message.
  With a reported SoH, "Measured: 95.8%" shows under it as a cross-check.
- Detect: **Energy dashboard battery**. A battery in Home Assistant's Energy dashboard whose energy sensors no
  sensor profile found is offered too; its energy in and out sensors become charged and discharged energy, and you
  search the Store for the model.

### Changed
- Card: tighter spacing between lines, rows and sections, about 7% shorter.
- New setups are named **"<Brand> Battery Ledger"** by default (was "<Brand> Battery"), which is the card's title.
  Existing setups keep their name; rename one under Settings → Devices & services → BatteryLedger. Entity IDs and
  friendly names don't change.
- Config entry version 1.6 (no change to stored data; the state of charge sensor is an optional new field).

## v0.1.19 (2026-11-20)

### TL;DR
- **Estimated Usage at EoSL**: the throughput expected by the End of Service Life, as a sensor and on the card
- Card: the chosen **Battery group** chip is light grey (was lavender)

### Added
- `sensor.battery_ledger_estimated_usage_at_eosl` (Estimated Usage at EoSL): throughput at the average rate so far
  until each battery group's End of Service Life, not capped at the warranted throughput. Attributes:
  `warranted_throughput_kwh`, `percent_of_warranted`, `estimated_service_life_years`, `low_confidence`. Each
  group's is in the groups attribute (`projected_esl_throughput_kwh`).
- Card: **Estimated usage at EoSL** under End of Service Life, e.g. "165,000 kWh" with "116% of warranted" below
  it, following the Battery group switcher.

### Changed
- Card: the chosen chip in the **Battery group** switcher is light grey.

## v0.1.18 (2026-11-20)

### TL;DR
- Estimated Service Life (ESL) defaults to **15 years** (was the warranty period)
- Card: the **Battery group** switcher moves under the title, with **All**, and a chosen group's figures fill the
  warranty, throughput and health sections
- `warranty_status` text: **On Track | Normal** (was "On Track / Normal")

### Changed
- **Estimated Service Life** until you set it: 15 years, or the setup's longest warranty period if that's longer
  (was the warranty period). Setups that haven't set it see End of Service Life move to 15 years after each
  group's warranty start, and the `esl` cost per kWh drop to match. Cost Per kWh (Export) only changes if Export
  Cost Basis is ESL or Cheapest; the default (Warranty) is unaffected. A value you've set is kept.
- Card, with more than one battery group: the **Battery group** switcher is under the title, with **All** (the
  whole setup, the default) and 1, 2, 3 …. A chosen group shows its own warranty rings, driver, end dates, use by
  age and usage, EoSL, **Remaining Warrantied Usage** bar and **Projected SoH** / warranty curve (with the chip
  comparing the battery's reported SoH to that group's curve), and the status chip shows that group's status. Cost
  stays for the whole setup. The chosen chip is lavender, clear of the blue of the by-age ring. In
  v0.1.17 the switcher only changed the warranty rows.
- `warranty_status` (on Estimated Usable Capacity) reads **On Track | Normal** (was "On Track / Normal"), in the
  sensor and on the card. If an automation or template compares that text, update it.
- Card: the Estimated Service Life box is narrower, without spin arrows.
- Battery group attributes: `projected_throughput_kwh` (throughput by the warranty end date at the average rate),
  for the card's group view.

## v0.1.17 (2026-11-20)

### TL;DR
- Card: **Estimated Service Life (ESL)**, **End of Service Life (EoSL)**, **Export Cost** and its basis
- Card: with more than one battery group, a **Battery group** switcher shows each group's end dates and use

### Added
- Card, Warranty section: **Estimated Service Life (ESL)** (a box admins can change; text for other users) and
  **End of Service Life (EoSL)**.
- Card, Cost section: **Export Cost** (Cost Per kWh (Export) and its basis: by age, by usage, ESL or SoH trend) and
  **Export Cost Basis** (a dropdown for admins: Warranty, Warranty by age, Warranty by usage, ESL, Cheapest).

### Fixed
- Card, with more than one battery group: the warranty end dates were the newest group's only. The rows beside the
  rings now show the whole setup (warranty driver, cycles per day, warranty used by age and by usage, ESL), and a
  **Battery group** switcher (1, 2, 3 …) shows the chosen group's warranty end dates, use by age and usage, and
  EoSL. One group: unchanged.

## v0.1.16 (2026-11-20)

### TL;DR
- **Cost Per kWh (Export)** (`sensor.battery_ledger_cost_per_kwh_export`): the battery's cost per kWh for the
  battery cost or minimum export price in EMHASS, HAEO or Energy Manager, with each basis as an attribute
- **Estimated Service Life (ESL)** and **End of Service Life (EoSL)**: how long you expect to keep the batteries,
  set in Configure or from a dashboard; **Export Cost Basis** chooses what the export cost publishes
- Setup file: Configure → **Export setup** and **Import a saved setup**, for a new server without a backup restore
- **Download diagnostics**, with module serials and costs removed, to attach to issues

### Added
- **Cost Per kWh (Export)** (`sensor.battery_ledger_cost_per_kwh_export`). Attributes give the cost per kWh on
  each basis: `age` (battery cost ÷ throughput projected by the warranty end date), `usage` (÷ warranted
  throughput), `esl` (÷ throughput projected to the End of Service Life) and `soh_trend` / `soh_trend_years`
  (empty until the SoH trend is added); `basis` names the one published, `driver` and `low_confidence` as on
  the other sensors. For the first 30 days (or with no usage yet) it's `usage`, as an early projection can be
  far too high for a minimum sell price. See README → Battery cost for exports.
- **Export Cost Basis** (`select.battery_ledger_export_cost_basis`): **Warranty (whichever ends first)**, the
  default and the higher of by age and by usage; **Warranty by age**; **Warranty by usage**; **Estimated Service
  Life (ESL)**; or **Cheapest** (the lowest of the warranty figure, ESL and SoH trend).
- **Estimated Service Life** (`number.battery_ledger_estimated_service_life`): years you expect to keep the
  batteries (1–30), one per setup, counted from each battery group's warranty start; the warranty period until
  set. **End of Service Life** (`sensor.battery_ledger_end_of_service_life`): the earliest group's, in calendar
  years from its warranty start; each group's in `groups`.
- Configure → **Service life and export cost**, for both settings. Changing them (there, or with the number and
  select entities) recalculates straight away, without reloading the setup.
- **Setup file:** Configure → **Export setup** downloads a `.json` file: the battery groups with their copied
  specs, warranty start dates and costs, the sensors chosen, which module (by serial number) is in which group,
  the name, currency style, card settings, Estimated Service Life and export cost basis. **Import a saved setup**
  (when adding BatteryLedger) uploads it: saved sensors are used where they exist on the new server, and modules
  keep their battery group by serial, so two groups of the same model are restored correctly. A file from a
  newer BatteryLedger is refused. A Home Assistant backup restore still needs none of this.
- **Download diagnostics**: the setup, source sensors' readings and the latest calculation, with module serials
  replaced by M1, M2… and costs removed.

### Changed
- Setup format 1.5: Estimated Service Life and the export cost basis are stored as options (migrated: ESL unset,
  basis Warranty).

## v0.1.15 (2026-11-19)

### TL;DR
- Detect: batteries on more than one tower or inverter can be set up as one battery group per tower, each with
  its own model, warranty start and cost (e.g. a Huawei tower and an iStore tower added later)
- Huawei and iStore: up to 18 (S0) or 36 (S1) modules; Sungrow SBR and SBH: up to 32 (4 stacks)

### Added
- Detect, with batteries on more than one tower or inverter: lists each (inverter, inverter model, tower,
  modules) and asks whether they were installed together. **Installed separately** gives one battery group per
  tower, with the units filled in; where more than one model fits a tower (e.g. Huawei LUNA2000-5-S0 or iStore
  IS-BATT-5000-ES), you choose. **Installed together** works as before.
- Huawei Solar: packs are counted per tower (storage unit 1 and 2), from the Store profile's new `tower` field.
  The inverter model comes from Home Assistant's device information.
- sigenergy2mqtt: with more than one inverter, each inverter's rated battery capacity and model are read (the
  Cloud API's modules don't say which inverter they're on), narrowed to the models the modules report.

### Changed
- Detect: when capacity ÷ pack count fits no battery (e.g. a SUN2000-MB0 with more towers than Huawei Solar
  has pack serial number sensors for), the rated capacity alone is used.
- Setup → Choose your battery modules: the example of a mix comes from the batteries listed, then other models
  of the same brand in the Store (was always "both BAT 8.0 and BAT 10.0").
- Bundled Store list: Huawei and iStore unit limits raised from 9 to 18 (S0) and 36 (S1) modules, with notes on
  tower and inverter limits; Huawei Solar's profile says which tower each pack position is in. Sungrow SBR and
  SBH raised from 8 to 32 modules (up to 4 stacks in parallel), with modules per stack in the SBR notes; SBR's
  minimum is 3 modules (was 2) and SBH's notes give 4–8 modules per stack, as in Sungrow's datasheets.
  sigenergy2mqtt's profile reads each inverter's rated battery capacity and model.

## v0.1.14 (2026-11-19)

### TL;DR
- Configure → **Battery groups**: fix a wrong unit count or warranty start date, remove a group, or add
  batteries installed later (more modules in a stack, or another stack), without deleting and re-creating the
  setup
- README: what a battery group is, with examples

### Added
- Configure → Battery groups, for a setup that's already running:
  - **Change or remove a group:** its number of units (checked against the battery's warranty, as in setup) and
    warranty start date. Removing a group also removes its cost and its battery modules; the only group can't
    be removed.
  - **Add a battery group:** choose the battery from the Store list (your setup's brands first), then the number
    of units, warranty start date and cost. The battery's spec is copied into the setup, as in setup. With Energy
    Manager, the second group's warranty start and cost are filled in from `input_datetime.battery_install_date_2`
    and `input_number.battery_install_cost_2`.
  - **Battery modules:** with per-module tracking (sigenergy2mqtt with the Sigen Cloud API), adding a group or
    adding units to one offers the module sensors your integration now reports that aren't tracked yet, matched
    to that group's model by rated capacity.

  Every sensor is recalculated after a change.
- README: a **Battery groups** section on what a group is (batteries of one model with the same warranty start
  date and cost, not a stack), with examples, and how unit limits, warranty limits and shared counters work.
- Setup and Configure: the units field says which unit counts are allowed and that batteries added on another
  date go in their own group.

## v0.1.13 (2026-11-19)

### TL;DR
- An SoH reading of 0% counts as no reading, and energy counters stuck at 0 get a note, so a source that
  isn't reporting no longer gives misleading figures
- Card: one cost per kWh figure when both are the same, and the Actual SoH tile says why there's no figure
  (not set up, not available from your integration, or no reading)

### Added
- Note code `energy_counters_zero`: the energy counters read 0 on a battery in service for 30 days or more,
  which usually means the source isn't reporting (seen with Energy Manager on a Sungrow inverter).

### Changed
- An SoH reading of 0% is treated as no reading. SoH Above Warranty Floor is then unavailable (it showed about
  −97%), and the card's Actual SoH tile shows no figure. Projected SoH (Today) comes from the warranty curve and
  is unaffected.
- Card: when cost per kWh by usage and by age are the same (e.g. the throughput allowance will all be used before
  the date end), the tile shows the one figure at the size of the other cost figures.
- Setup and Configure → Sensors and currency: the currency style explanation describes Currency code first, in
  the same order as the options.
- Card: with no SoH reading, the Actual SoH tile says why (was "No SoH sensor chosen for this setup"), using the
  setup's integration and what the Store says it provides for your battery:
  - "Not Configured ⚙" when the integration has an SoH sensor that isn't chosen. For admins it's a link to this
    setup on BatteryLedger's integration page (Configure → Sensors and currency)
  - "Not available for Huawei" (for example) when the battery doesn't provide SoH through that integration,
    including Energy Manager with a Huawei or iStore battery
  - "No SoH reading from Energy Manager" (for example) when a sensor is chosen but reports nothing, or 0%, for a
    battery that does provide SoH: a setup issue with that integration
  - "No SoH sensor configured" for a manual setup
- Bundled Store list: sensor profiles can list sensors they can't provide for some brands (`unavailable`).
  Huawei Solar and Energy Manager list SoH for Huawei and iStore, as the LUNA2000 doesn't report it.

## v0.1.12 (2026-11-18)

### TL;DR
- Detect now says that the sensors it turns on stay on, also after BatteryLedger is removed
- README: Marketplace install button fixed, with the HACS button as a fallback
- Automatic code and workflow security checks (Ruff, zizmor, CodeQL); workflows hardened
- Fixed: the Release workflow couldn't attach `battery_ledger.zip` (its permission had landed in the wrong
  place); actionlint now checks the workflows' syntax to catch that kind of mistake

### Changed
- Detect: the step that offers to turn on sensors says they stay on afterwards, even if BatteryLedger is
  removed, and how to turn them off (Settings → Entities). BatteryLedger never turns them off itself.
- README: the Marketplace button names the repository's category (Integration), and the HACS button is
  mentioned as working on Home Assistant 2026.11 and newer too.
- Code: lists paired up in the warranty maths and setup must be the same length (`zip(..., strict=True)`), so a
  mismatch raises an error instead of silently dropping a battery group.
- Code is checked with [Ruff](https://docs.astral.sh/ruff/) on every push and pull request (`ruff.toml`),
  including its security rules, so issues like that are flagged automatically. Two internal `assert`s became
  explicit checks.
- Security checks: a new Security workflow audits the GitHub workflows with
  [zizmor](https://docs.zizmor.sh/) and scans the code with CodeQL (also weekly). The workflows were hardened
  to match: values pass to scripts through environment variables, each job gets only the permissions it needs,
  and checkouts don't keep the GitHub token unless they push. The card's JavaScript gets a syntax check, and
  Dependabot also keeps the test requirements up to date.

### Fixed
- Release workflow: the `contents: write` permission for attaching `battery_ledger.zip` was under the
  release trigger instead of the job, so publishing a release failed with HTTP 403. A new actionlint check in
  the Security workflow catches misplaced keys like that.

## v0.1.11 (2026-11-18)

### TL;DR
- Card settings: show dates as day month year (18 Jul 2035) instead of your Home Assistant date format, and
  5 decimal places for cost per kWh
- Card: cost per kWh reads "by usage" and "by age", and the cost labels end with a colon

### Added
- Card settings (the cog): **Date display**, either Home Assistant format (the default: your profile's date
  format, as before) or day month year, e.g. 18 Jul 2035, with the month's short name in your language.
- Card settings: 5 decimal places for cost per kWh.
- Card: the BatteryLedger version (e.g. v0.1.11) at the bottom right, with the settings cog just to its left.

### Changed
- Card: the cost per kWh figures are labelled "by usage" (cost ÷ warranted throughput, was "rated") and "by age"
  (cost ÷ throughput projected by the end of the warranty, was "projected").
- Card labels end with a colon: "Cost per kWh:", "Value used to date:", "Remaining Value:", and in the settings
  "Cost per kWh decimal places:" and "Display Sections:" (was "Sections").
- Card: the Value used to date, Remaining Value and Cost per kWh figures are centred vertically below their
  labels, in tiles of equal height (the two cost per kWh lines a little apart), and the health
  bar's floor reads "70% End of Warranty" (the battery's own end-of-warranty capacity, as before).

## v0.1.10 (2026-11-18)

### TL;DR
- The throughput warranty driver reads "Throughput (Cycles)" (was "Throughput (Cycle Abuse)"): update any
  template that compares against the old text
- Card: warranty rows regrouped and relabelled, the end date driving the warranty in red, "Warranty Ends
  (10 years)" from your battery's warranty period, and dates in your Home Assistant date format

### Changed
- The throughput warranty driver is "Throughput (Cycles)" instead of "Throughput (Cycle Abuse)", on the card and
  in the `degradation_driver` attribute of `estimated_usable_capacity`. **Templates or automations that compare
  against "Throughput (Cycle Abuse)" need updating.** "Age (Time Elapsed)" is unchanged.
- Card: the warranty rows are Warranty Driver and Cycles per day (Average), then each warranty end date above
  the share of the warranty it comes from: Warranty Ends (10 years) and Warranty Used (by age), then Warranty
  Ends (by usage) and Warranty Used (by usage), with a thin line above each end date. Labels start in line,
  with the ring colour dots to their left. The end date that comes first, the one driving the warranty, is
  shown in red.
- Card: the date end is labelled with the battery's warranty period, e.g. "Warranty Ends (10 years)" (was
  "Warranty Ends (Date)"), and "Warranty Ends (Usage)" is "Warranty Ends (by usage)".
- Card: warranty end dates follow each user's Home Assistant date format (Profile → Date format), as the rest of
  Home Assistant does: Day-Month-Year shows 18/7/2035, for example, instead of 2035-07-18.
- Card labels: "Warranty by Time Elapsed" is "Warranty Used (by age)", "Warranty by Throughput Used" is
  "Warranty Used (by usage)", "Battery cycles per day (Average)" is "Cycles per day (Average)", and "Remaining
  Rated Throughput" is "Remaining Warrantied Usage:".
- Workflows use `actions/github-script` v9 (Dependabot, #1).

## v0.1.9 (2026-11-18)

### TL;DR
- New **Detect** setup: BatteryLedger reads your battery integration (pack count, capacity, inverter model,
  Energy Manager's brand) to suggest the battery model and module count, and can turn on the sensors it needs
- Each battery group has its own cost, so batteries added later carry their own cost and warranty clock;
  Energy Manager's install dates and costs pre-fill them. Existing setups move their cost to the first group
- Card: "Warranty Ends (Usage)", when the throughput limit is reached at your average use, beside "Warranty
  Ends (Date)"; "Warranty Used" and "Value used to date" labels; the BatteryLedger logo

### Added
- **Detect from my battery's integration**, a new first choice in setup. It finds the systems of every integration
  BatteryLedger knows and suggests the battery model and number of modules, for you to confirm:
  - Sigenergy Local Modbus: each inverter's pack count and rated battery capacity (capacity per module), with the
    inverter model type telling SigenStor from Neo. Two inverters get a group each when together they're over a
    model's per-inverter limit
  - sigenergy2mqtt: each module's rated capacity, so mixed models are recognised
  - Huawei / iStore (wlcrs): rated capacity ÷ battery packs with a serial number (S0 or S1). Rebadged batteries
    with identical warranty figures are shown as detected; the S0, whose Huawei and iStore warranties differ, is
    left for you to choose
  - BYD Battery Box: towers × modules; AlphaESS: module count; Energy Manager and others: rated capacity alone,
    narrowed by Energy Manager's inverter brand
- Detect lists the sensors it needs that are off by default in their integration and, with your OK, turns them
  on, checks for their readings after 45 seconds and again 45 seconds later, then carries on. Sensors you
  turned off yourself are never touched
- Energy Manager's `battery_install_cost`, `battery_install_date_2` and `battery_install_cost_2` pre-fill the
  first and second battery groups (as `battery_install_date` already did)
- Configure → **Battery costs**: one form per battery group
- Card: **Warranty Ends (Usage)** shows when the throughput limit would be reached at the average daily use so
  far (it can be before or after the date end); the time-based row is **Warranty Ends (Date)**. Each battery
  group's `throughput_end_date` is in the `groups` attribute
- Bundled Store list: sensor profiles gain the readings Detect uses (Sigenergy Local Modbus pack count, model
  type and per-inverter capacity; wlcrs pack serial positions; BYD towers and modules; AlphaESS module count;
  Energy Manager's inverter brand, install costs and second install date)

### Changed
- Cost belongs to each battery group (setup asks for it with the units and warranty start, not on the System
  step). Existing setups move their cost to the first group (config entry 1.4); a group added later starts
  without one until you set it under Configure → Battery costs. Each group's cost is used up on its own warranty
  driver; cost per kWh covers the groups that have a cost. The `groups` attribute gains `cost` and
  `cost_consumed`
- Card: the BatteryLedger logo replaces the battery icon at the top left.
- Card: the dial reads "Warranty Used", and "Cost Consumed To Date" is "Value used to date" (the sensor keeps its
  name and entity ID).

## v0.1.8 (2026-11-17)

### TL;DR
- BatteryLedger waits for your battery integration's sensors at startup, and rides out dropouts, instead of
  briefly showing figures from the wrong energy counter

### Changed
- At startup, a battery integration that hadn't connected yet looked like a sensor that wasn't set up: with
  the discharged counter still unavailable, the warranty briefly used charged energy (and per-module tracking
  fell back to plant totals), leaving a blip in history. BatteryLedger now waits until every chosen source
  sensor has reported, up to 5 minutes after Home Assistant starts, with its sensors unavailable meanwhile.
  A source that drops out later keeps its last reading, so the basis no longer flips
- README: card screenshot

## v0.1.7 (2026-11-17)

No v0.1.6 release was published; its changes are in this one.

### TL;DR
- Cost Consumed To Date (and Remaining Value) follow the warranty driver, so an age-driven battery uses up its
  cost by time elapsed rather than by throughput
- Card: settings cog at the bottom right; "Battery cycles per day (Average)" and "Projected SoH (Today)"
- Bundled Store list adds SigenStor Neo, AlphaESS, Deye, GoodWe, BYD and Fronius batteries, with their
  integrations' sensor profiles; Huawei LUNA2000 names
- Estimated Usable Capacity shows an icon again

### Changed
- Cost Consumed To Date followed throughput used even when age drove the warranty, so it understated the cost
  used up (13.4% of the warranty gone, 10.2% of the cost). It now uses up each battery group's cost by that
  group's warranty life used (the larger of time elapsed and throughput used), and Remaining Value
  (`estimated_remaining_value`) follows. `percent_of_rated_life_used` is still the throughput share, and the
  cost per kWh sensors are unchanged
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
- Bundled Store list: the Reserva Pro module is 3.98 kWh usable (about 4.0 kWh nominal), 3-8 per battery, and
  works with single-phase Primo GEN24 Plus (12.0-20.0) as well as three-phase inverters.
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
