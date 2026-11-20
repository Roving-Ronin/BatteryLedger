"""Constants for BatteryLedger."""

from datetime import timedelta

DOMAIN = "battery_ledger"

# Config entry schema version. A change to what an entry stores (data/options, including
# the copied battery specs) bumps one of these and adds one step to async_migrate_entry
# in __init__.py, with a test feeding it an entry in the old format.
CONFIG_ENTRY_VERSION = 1
CONFIG_ENTRY_MINOR_VERSION = 6
NAME = "BatteryLedger"

STORE_INDEX_URL = "https://roving-ronin.github.io/BatteryLedger-Store/index.json"
STORE_SITE_URL = "https://roving-ronin.github.io/BatteryLedger-Store/"
STORE_REPO = "Roving-Ronin/BatteryLedger-Store"
STORE_ISSUE_FORM_URL = f"https://github.com/{STORE_REPO}/issues/new"
SUPPORTED_INDEX_FORMAT = 1

STORE_REFRESH_INTERVAL = timedelta(hours=24)
RECALC_INTERVAL = timedelta(hours=1)
RECALC_DEBOUNCE_SECONDS = 60
# After Home Assistant starts, how long to wait for every configured source sensor to report
# before calculating with whatever is available.
STARTUP_WAIT = timedelta(minutes=5)

# Config entry data keys
CONF_GROUPS = "groups"
CONF_SPEC = "spec"
CONF_UNITS = "units"
CONF_INSTALL_DATE = "install_date"
CONF_COST = "cost"  # per battery group (entry 1.4+); a setup-wide value before that
CONF_CURRENCY = "currency"  # legacy (entries before 1.3): explicit currency code override
CONF_CURRENCY_STYLE = "currency_style"
CURRENCY_STYLE_CODE = "code"
CURRENCY_STYLE_SYMBOL = "symbol"

# Symbols for the cost-per-kWh unit when the user prefers a symbol (e.g. $/kWh).
# Money sensors always use the ISO code: Home Assistant then shows the right symbol for
# each user's locale (AUD -> "$2,719.53" in English (Australia)); a bare "$" unit breaks that.
CURRENCY_SYMBOLS = {
    "AUD": "$", "NZD": "$", "USD": "$", "CAD": "$", "SGD": "$", "HKD": "$", "MXN": "$",
    "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "INR": "₹", "KRW": "₩", "ZAR": "R",
    "BRL": "R$", "CHF": "CHF", "SEK": "kr", "NOK": "kr", "DKK": "kr", "PLN": "zł", "CZK": "Kč",
    "HUF": "Ft", "ILS": "₪", "TRY": "₺", "PHP": "₱", "THB": "฿", "MYR": "RM", "IDR": "Rp", "VND": "₫",
}
CONF_CHARGED_ENTITY = "charged_energy_entity"
CONF_DISCHARGED_ENTITY = "discharged_energy_entity"
CONF_CAPACITY_ENTITY = "reported_capacity_entity"
CONF_SOH_ENTITY = "soh_entity"
CONF_SOC_ENTITY = "soc_entity"  # the whole battery's state of charge (entry 1.6+), for measured capacity
CONF_PROFILE = "sensor_profile"
CONF_MODULES = "modules"
CONF_USE_MODULES = "use_modules"
# Options (entry 1.5+), changed from Configure or the number / select entities without a reload
CONF_ESL_YEARS = "esl_years"  # Estimated Service Life in years; None = ledger.default_esl_years (15 years)
CONF_EXPORT_SETTING = "export_cost_basis"  # ledger.EXPORT_* ("warranty", "esl", "cheapest")
LIVE_OPTIONS = (CONF_ESL_YEARS, CONF_EXPORT_SETTING)
ESL_MIN_YEARS, ESL_MAX_YEARS, ESL_STEP_YEARS = 1, 30, 0.5
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

# Attribute values and states copied from the original YAML package, so existing templates and
# dashboards keep working. These are a compatibility contract, not UI text: don't translate or
# reword them (the newer enum sensors carry translated codes instead).
# "Throughput (Cycles)" was the YAML package's "Throughput (Cycle Abuse)" until 0.1.9 (changed on purpose).
YAML_DRIVER_TEXT = {"age": "Age (Time Elapsed)", "throughput": "Throughput (Cycles)"}
YAML_STATUS_TEXT = {
    "on_track": "On Track | Normal",
    "ahead_of_time": "Degrading Faster Than Time Curve",
    "expired": "Warranty Ended",  # not in the YAML package (it had no end-of-warranty state)
}
YAML_HARDWARE_TEXT = {"match": "Match Verified", "mismatch": "Mismatch Detected"}

# Config entry 1.2 -> 1.3 (BatteryLedger 0.1.3): sensors removed because they duplicated the original YAML
# package's attributes. Their registry entries are removed so they don't linger as "no longer provided".
REMOVED_SENSOR_KEYS_1_3 = (
    "rated_life_used", "estimated_remaining_value", "remaining_usable_capacity",
    "degradation_driver", "warranty_status",
)
