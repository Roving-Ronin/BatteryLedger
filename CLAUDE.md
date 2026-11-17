# CLAUDE.md

Guidance for Claude Code when working in this repository. This file holds the rules and traps;
the README explains features to users.

## Project

BatteryLedger is a Home Assistant custom integration (`custom_components/battery_ledger`) that tracks
home battery warranty use, warranty-floor capacity, cost per kWh and remaining value. Battery specs and
sensor profiles come from the separate **BatteryLedger Store** repo (`Roving-Ronin/BatteryLedger-Store`),
published as `https://roving-ronin.github.io/BatteryLedger-Store/index.json`.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
python -m pytest -q                      # all tests (real in-process Home Assistant, no network)
python -m compileall -q custom_components/battery_ledger
```

Tests run against a real test Home Assistant (pytest-homeassistant-custom-component), never a
`MagicMock` hass: a mock accepts calls real HA rejects. `tests/conftest.py` makes every Store refresh
fail (`offline_store`), so tests use the bundled snapshot; keep it that way.

## Module map

| File | Role |
|---|---|
| `ledger.py` | **All warranty / degradation / cost maths.** Pure Python, no HA imports, unit-tested directly. Never re-implement this maths elsewhere |
| `detect.py` | Finds sensors from Store sensor profiles (unique-ID templates) and assigns modules to battery groups. Pure |
| `store_client.py` | Downloads, caches and searches the Store index; bundled snapshot fallback |
| `runtime.py` | Per-entry: reads source sensors, converts units, calls `ledger.compute`, signals sensors |
| `sensor.py` | Entities only: values come from the `LedgerResult` |
| `config_flow.py` | Setup wizard and options flow |
| `repairs.py` | Accepting revised Store specs |
| `data/index_snapshot.json` | Copy of the Store index shipped with each release |

## Rules

### Sensors and privacy
- **Match sensors by entity registry `unique_id`, never `entity_id`.** Users rename entities.
- Profile templates use placeholders (`{entry}`, `{device}`, `{prefix}`, `{plant}`, `{inverter}`,
  `{station}`, `{serial}`). **Nothing install-specific ever goes to the Store**: no serial numbers,
  Sigen station IDs, config entry IDs, install dates, costs or energy totals. Anything submitted from
  Home Assistant is previewed to the user first.
- Module serials stay local. Attributes that contain them are listed in `_unrecorded_attributes`.

### Specs
- A chosen spec is **copied into the config entry** (pinned). Store revisions reach an existing setup
  only through the Repairs flow, which shows the changed fields. Never update an entry's spec silently.
- Manually entered specs have IDs starting `custom-` and `spec_version` 0; they never get Store
  revision repairs.
- Throughput basis: when the warranty doesn't state it, or the matching sensor is missing, use
  **charged** energy (the larger counter, conservative) and record a note code.

### Config entry migration
- Versions live in `const.py` (`CONFIG_ENTRY_VERSION` / `CONFIG_ENTRY_MINOR_VERSION`). Changing what an
  entry stores (including the copied spec format) = bump one of them + one step in
  `async_migrate_entry` + a test in `tests/test_migration.py` with an old-format entry.
- Migrations are deterministic and idempotent and never drop user data. An entry from a newer version
  is refused, not guessed at.

### UI text
- **No English inside Python code.** Wording goes in `strings.json`; copy it to
  `translations/en.json` (the Pull Requests workflow checks they match). Description placeholders carry
  data only (numbers, names, dates, IDs, ✓/✗). Where wording differs by case, use a separate step or
  error key rather than building text in code. Don't use ICU `plural`/`select` syntax: core HA doesn't.
- Sensor attribute `notes` are codes (`ledger.NOTE_*`), documented in the README.
- Dates in descriptions are ISO (`2025-07-18`). The date picker's display format comes from each
  user's HA profile, not from the integration.

### Home Assistant patterns
- `dt_util.now()` for local dates, never `datetime.now()`.
- Read source sensors with their unit and convert via `EnergyConverter`.
- Recalculation is debounced (`RECALC_DEBOUNCE_SECONDS`); energy counters update every few seconds.

## Releases and changelog
- Publish a GitHub release tagged `vX.Y.Z`; the Release workflow writes the version into
  `manifest.json`, attaches `battery_ledger.zip` (what the Marketplace / HACS installs) and commits the
  version back. Don't edit the manifest version by hand.
- Refresh `data/index_snapshot.json` from the published Store index before a release.
- `CHANGELOG.md`: every release opens with a `### TL;DR`, rewritten as a whole when entries are added.

## Repo conventions
- Issue templates use GitHub's default labels only (`bug`, `enhancement`, `question`); don't introduce
  custom labels for workflows.
- Never commit or push without the maintainer's explicit approval.
