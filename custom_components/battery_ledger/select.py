"""Export cost basis: what Cost Per kWh (Export) publishes (warranty, Estimated Service Life or the cheapest).

Changing it recalculates the sensors without reloading the setup.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_EXPORT_SETTING, ENTITY_ID_PREFIX
from .ledger import EXPORT_SETTINGS, EXPORT_WARRANTY
from .runtime import LedgerRuntime
from .sensor import device_info

KEY = "export_cost_basis"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ExportCostBasis(entry.runtime_data)])


class ExportCostBasis(SelectEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = KEY
    _attr_icon = "mdi:cash-fast"
    _attr_options = list(EXPORT_SETTINGS)

    def __init__(self, runtime: LedgerRuntime) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_{KEY}"
        self.entity_id = f"select.{ENTITY_ID_PREFIX}_{KEY}"
        self._attr_device_info = device_info(runtime)

    async def async_added_to_hass(self) -> None:
        # Also changed from Configure: follow each recalculation
        self.async_on_remove(async_dispatcher_connect(self.hass, self.runtime.signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str:
        value = self.runtime.config.get(CONF_EXPORT_SETTING)
        return value if value in EXPORT_SETTINGS else EXPORT_WARRANTY

    async def async_select_option(self, option: str) -> None:
        entry = self.runtime.entry
        self.hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_EXPORT_SETTING: option})
        self.async_write_ha_state()
