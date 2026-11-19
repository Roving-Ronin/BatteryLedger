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
pip install ruff && ruff check .        # lint incl. security rules (ruff.toml); Tests workflow runs it
pip install zizmor actionlint-py && zizmor . && actionlint   # workflow security + syntax; Security workflow runs both
```

CI on every push and PR: Tests (Ruff, card syntax, pytest), Security (zizmor, CodeQL; also weekly),
hassfest and the HACS validator.

Tests run against a real test Home Assistant (pytest-homeassistant-custom-component), never a
`MagicMock` hass: a mock accepts calls real HA rejects. `tests/conftest.py` makes every Store refresh
fail (`offline_store`), so tests use the bundled snapshot; keep it that way.

## Module map

| File | Role |
|---|---|
| `ledger.py` | **All warranty / degradation / cost maths.** Pure Python, no HA imports, unit-tested directly. Never re-implement this maths elsewhere |
| `detect.py` | Finds sensors from Store sensor profiles (unique-ID templates), per-inverter readings, and assigns modules to battery groups. Pure |
| `suggest.py` | Suggests battery model and unit count from capacity, pack/module counts and inverter model text, for the user to confirm. Pure |
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
  `{station}`, `{serial}`, `{mac}`). **Nothing install-specific ever goes to the Store**: no serial numbers,
  Sigen station IDs, config entry IDs, install dates, costs or energy totals. Anything submitted from
  Home Assistant is previewed to the user first.
- Module serials stay local. Attributes that contain them are listed in `_unrecorded_attributes`.

### Entities
- Entity IDs are `sensor.battery_ledger_<key>` (`ENTITY_ID_PREFIX`), keys and attribute names taken from
  the original YAML package. **Renaming a key or entity ID breaks users' dashboards**: avoid it; if it's
  unavoidable, add a migration step that moves the registry entry (see `_migrate_entities_1_2`).
- **`YAML_SENSORS` must stay identical to the original YAML package**: same state values, units, icons,
  attribute names and attribute values (`YAML_*_TEXT` in `const.py`), no `device_class` (except monetary
  with the currency-code style), no extra attributes, no attribution. New detail goes on `EXTRA_SENSORS`.
  `test_flow_and_sensors` checks this.
- Friendly names are the translated device name ("Battery") + Title Case entity name, never the brand or
  the setup's title.

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
- **No English inside Python code** (the one exception: the `YAML_*_TEXT` compatibility values in
  `const.py`, which are a data contract with existing templates). Wording goes in `strings.json`; copy it to
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
- A PR that adds a CHANGELOG section is followed by its release: head the section `## vX.Y.Z (YYYY-MM-DD)` with
  the date it's prepared, never "(unreleased)".

## Workflow security
- Never put `${{ ... }}` expressions inside `run:` scripts: pass them through `env:` and use `"$VAR"`.
  Issue titles, bodies and comments are attacker-controlled; read them only in `github-script` (as JS
  values) or via `env:`.
- `permissions: {}` at workflow level and grant each job only what it needs.
- `actions/checkout` with `persist-credentials: false`, unless the job pushes with git (mark it
  `# zizmor: ignore[artipacked]` with the reason).
- Actions are pinned by tag (`.github/zizmor.yml`), kept current by Dependabot.

## Repo conventions
- Issue templates use GitHub's default labels only (`bug`, `enhancement`, `question`); don't introduce
  custom labels for workflows.
- Never commit or push without the maintainer's explicit approval.
