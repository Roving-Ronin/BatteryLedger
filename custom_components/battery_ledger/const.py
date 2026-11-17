"""Constants for BatteryLedger."""

from datetime import timedelta

DOMAIN = "battery_ledger"

# Config entry schema version. A change to what an entry stores (data/options, including
# the copied battery specs) bumps one of these and adds one step to async_migrate_entry
# in __init__.py, with a test feeding it an entry in the old format.
CONFIG_ENTRY_VERSION = 1
CONFIG_ENTRY_MINOR_VERSION = 2
NAME = "BatteryLedger"

STORE_INDEX_URL = "https://roving-ronin.github.io/BatteryLedger-Store/index.json"
STORE_SITE_URL = "https://roving-ronin.github.io/BatteryLedger-Store/"
STORE_REPO = "Roving-Ronin/BatteryLedger-Store"
STORE_ISSUE_FORM_URL = f"https://github.com/{STORE_REPO}/issues/new"
SUPPORTED_INDEX_FORMAT = 1

STORE_REFRESH_INTERVAL = timedelta(hours=24)
RECALC_INTERVAL = timedelta(hours=1)
RECALC_DEBOUNCE_SECONDS = 60

# Config entry data keys
CONF_GROUPS = "groups"
CONF_SPEC = "spec"
CONF_UNITS = "units"
CONF_INSTALL_DATE = "install_date"
CONF_COST = "cost"
CONF_CURRENCY = "currency"
CONF_CHARGED_ENTITY = "charged_energy_entity"
CONF_DISCHARGED_ENTITY = "discharged_energy_entity"
CONF_CAPACITY_ENTITY = "reported_capacity_entity"
CONF_SOH_ENTITY = "soh_entity"
CONF_PROFILE = "sensor_profile"
CONF_MODULES = "modules"
CONF_USE_MODULES = "use_modules"
# Keys inside each CONF_MODULES item
MOD_ID = "id"
MOD_GROUP = "group"
MOD_DISCHARGED = "discharged_entity"
MOD_SOC = "soc_entity"

SPEC_SOURCE_MANUAL = "manual"
MANUAL_ID_PREFIX = "custom-"

ANY = "any"
MANUAL = "manual"

SIGNAL_UPDATE = f"{DOMAIN}_update_{{entry_id}}"

# Entity IDs are sensor.battery_ledger_<key> (HA appends _2, _3 ... for further setups).
ENTITY_ID_PREFIX = "battery_ledger"

# Config entry 1.1 -> 1.2 (BatteryLedger 0.1.1 -> 0.1.2): sensor keys renamed back to the
# original YAML package's names. old key -> (new key, old default entity-id suffix)
SENSOR_KEY_RENAMES_1_2 = {
    "throughput_limit": ("total_rated_throughput", "warranted_throughput"),
    "throughput_used": ("rated_throughput_used", "throughput_used"),
    "throughput_remaining": ("remaining_rated_throughput", "throughput_remaining"),
    "throughput_used_pct": ("rated_life_used", "warranty_throughput_used"),
    "time_elapsed_pct": ("warranty_time_elapsed", "warranty_time_elapsed"),
    "projected_throughput": ("projected_warranted_throughput", "projected_warranty_throughput"),
    "cost_per_kwh_rated": ("cost_per_kwh_rated", "cost_per_kwh_warranted"),
    "cost_per_kwh_projected": ("cost_per_kwh_projected", "cost_per_kwh_projected"),
    "cost_consumed": ("cost_consumed_to_date", "cost_consumed"),
    "remaining_value": ("estimated_remaining_value", "remaining_value"),
    "initial_usable_capacity": ("initial_usable_capacity", "initial_usable_capacity"),
    "warranty_floor_capacity": ("remaining_usable_capacity", "warranty_floor_capacity"),
    "warranty_floor_pct": ("estimated_usable_capacity", "warranty_floor_health"),
    "degradation_driver": ("degradation_driver", "warranty_driver"),
    "warranty_status": ("warranty_status", "warranty_status"),
    "hardware_validation": ("hardware_capacity_validation", "hardware_check"),
    "worst_module_throughput_used": ("most_used_module_throughput", "most_used_module_throughput"),
    "module_soc_spread": ("module_soc_spread", "module_soc_spread"),
    "health_margin": ("soh_above_warranty_floor", "health_above_warranty_floor"),
}
