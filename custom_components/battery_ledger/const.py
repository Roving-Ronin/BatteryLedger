"""Constants for BatteryLedger."""

from datetime import timedelta

DOMAIN = "battery_ledger"
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
