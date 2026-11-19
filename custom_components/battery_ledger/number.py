"""Estimated Service Life (ESL): how many years the battery is expected to be kept, one value per setup.

Counted from each battery group's warranty start, so a stack added later has its own End of Service Life.
Changing it recalculates the sensors without reloading the setup.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ESL_YEARS, CONF_SPEC, ENTITY_ID_PREFIX, ESL_MAX_YEARS, ESL_MIN_YEARS, ESL_STEP_YEARS
from .runtime import LedgerRuntime
from .sensor import device_info

KEY = "estimated_service_life"


def default_esl_years(runtime: LedgerRuntime) -> float:
    """Without a setting: the (longest) warranty period of the setup's batteries."""
    return float(max(g[CONF_SPEC]["warranty"]["years"] for g in runtime.groups))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([EstimatedServiceLife(entry.runtime_data)])


class EstimatedServiceLife(NumberEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = KEY
    _attr_icon = "mdi:calendar-clock"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = ESL_MIN_YEARS
    _attr_native_max_value = ESL_MAX_YEARS
    _attr_native_step = ESL_STEP_YEARS
    _attr_native_unit_of_measurement = UnitOfTime.YEARS

    def __init__(self, runtime: LedgerRuntime) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_{KEY}"
        self.entity_id = f"number.{ENTITY_ID_PREFIX}_{KEY}"
        self._attr_device_info = device_info(runtime)

    async def async_added_to_hass(self) -> None:
        # Also changed from Configure: follow each recalculation
        self.async_on_remove(async_dispatcher_connect(self.hass, self.runtime.signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        value = self.runtime.config.get(CONF_ESL_YEARS)
        return float(value) if value else default_esl_years(self.runtime)

    async def async_set_native_value(self, value: float) -> None:
        entry = self.runtime.entry
        self.hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_ESL_YEARS: float(value)})
        self.async_write_ha_state()
