"""BatteryLedger sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY, CONF_SPEC, DOMAIN, ENTITY_ID_PREFIX, MOD_SOC, NAME
from .ledger import (
    DRIVER_AGE,
    DRIVER_THROUGHPUT,
    HW_MATCH,
    HW_MISMATCH,
    STATUS_AHEAD,
    STATUS_EXPIRED,
    STATUS_ON_TRACK,
    LedgerResult,
)
from .runtime import LedgerRuntime


def _r(value, nd):
    return None if value is None else round(value, nd)


@dataclass(frozen=True, kw_only=True)
class LedgerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[LedgerResult], Any]
    attrs_fn: Callable[[LedgerResult], dict[str, Any]] | None = None
    unit_fn: Callable[[str], str] | None = None  # given the currency


def _groups_attr(res: LedgerResult) -> dict[str, Any]:
    return {"groups": [g.as_attributes() for g in res.groups], "notes": res.notes}


def _energy(key: str, icon: str, value_fn, attrs_fn=None, precision: int = 0,
            device_class=SensorDeviceClass.ENERGY) -> LedgerSensorDescription:
    return LedgerSensorDescription(
        key=key, translation_key=key, icon=icon, device_class=device_class,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, suggested_display_precision=precision,
        value_fn=value_fn, attrs_fn=attrs_fn)


def _pct(key: str, icon: str, value_fn, attrs_fn=None, precision: int = 2) -> LedgerSensorDescription:
    return LedgerSensorDescription(
        key=key, translation_key=key, icon=icon, native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=precision, value_fn=value_fn, attrs_fn=attrs_fn)


# Names and attributes follow the original YAML package (battery_ledger_ instead of sigen_battery_).
SENSORS: tuple[LedgerSensorDescription, ...] = (
    _energy("total_rated_throughput", "mdi:battery-charging-100", lambda r: _r(r.limit_kwh, 0),
            lambda r: {"total_pack_count": r.total_units}),
    _energy("remaining_rated_throughput", "mdi:battery-arrow-down", lambda r: _r(r.remaining_kwh, 0)),
    _energy("rated_throughput_used", "mdi:battery-sync", lambda r: _r(r.used_kwh, 1), _groups_attr),
    _energy("projected_warranted_throughput", "mdi:chart-timeline-variant", lambda r: _r(r.projected_kwh, 0),
            lambda r: {"average_daily_kwh": _r(r.avg_daily_kwh, 2), "low_confidence": r.low_confidence}),
    LedgerSensorDescription(
        key="cost_per_kwh_rated", translation_key="cost_per_kwh_rated", icon="mdi:currency-usd",
        suggested_display_precision=4, unit_fn=lambda c: f"{c}/kWh",
        value_fn=lambda r: _r(r.cost_per_kwh_rated, 4)),
    LedgerSensorDescription(
        key="cost_per_kwh_projected", translation_key="cost_per_kwh_projected", icon="mdi:currency-usd",
        suggested_display_precision=4, unit_fn=lambda c: f"{c}/kWh",
        value_fn=lambda r: _r(r.cost_per_kwh_projected, 4)),
    LedgerSensorDescription(
        key="cost_consumed_to_date", translation_key="cost_consumed_to_date", icon="mdi:cash-minus",
        device_class=SensorDeviceClass.MONETARY, suggested_display_precision=2, unit_fn=lambda c: c,
        value_fn=lambda r: _r(r.cost_consumed, 2),
        attrs_fn=lambda r: {"percent_of_rated_life_used": _r(r.used_pct, 2),
                            "estimated_remaining_value": _r(r.remaining_value, 2)}),
    LedgerSensorDescription(
        key="estimated_remaining_value", translation_key="estimated_remaining_value", icon="mdi:cash-clock",
        device_class=SensorDeviceClass.MONETARY, suggested_display_precision=2, unit_fn=lambda c: c,
        value_fn=lambda r: _r(r.remaining_value, 2),
        attrs_fn=lambda r: {"remaining_value_by_warranty_life": _r(r.remaining_value_by_life, 2)}),
    _pct("rated_life_used", "mdi:progress-clock", lambda r: _r(r.used_pct, 2)),
    _pct("warranty_time_elapsed", "mdi:calendar-clock", lambda r: _r(r.time_elapsed_pct, 2)),
    _energy("initial_usable_capacity", "mdi:battery-heart-variant", lambda r: _r(r.initial_usable_kwh, 2),
            precision=2, device_class=SensorDeviceClass.ENERGY_STORAGE),
    _pct("estimated_usable_capacity", "mdi:battery-analytics", lambda r: _r(r.floor_pct, 1),
         lambda r: {"remaining_usable_kwh": _r(r.floor_usable_kwh, 2), "degradation_driver": r.driver,
                    "warranty_status": r.status, **_groups_attr(r)}, precision=1),
    _energy("remaining_usable_capacity", "mdi:battery-analytics", lambda r: _r(r.floor_usable_kwh, 2),
            precision=2, device_class=SensorDeviceClass.ENERGY_STORAGE),
    LedgerSensorDescription(
        key="degradation_driver", translation_key="degradation_driver", icon="mdi:car-brake-alert",
        device_class=SensorDeviceClass.ENUM, options=[DRIVER_AGE, DRIVER_THROUGHPUT],
        value_fn=lambda r: r.driver),
    LedgerSensorDescription(
        key="warranty_status", translation_key="warranty_status", icon="mdi:shield-half-full",
        device_class=SensorDeviceClass.ENUM, options=[STATUS_ON_TRACK, STATUS_AHEAD, STATUS_EXPIRED],
        value_fn=lambda r: r.status),
)

HARDWARE_SENSOR = LedgerSensorDescription(
    key="hardware_capacity_validation",
    translation_key="hardware_capacity_validation",
    icon="mdi:shield-check-outline",
    device_class=SensorDeviceClass.ENUM,
    entity_category=EntityCategory.DIAGNOSTIC,
    options=[HW_MATCH, HW_MISMATCH],
    value_fn=lambda r: r.hardware,
    attrs_fn=lambda r: {"configured_rated_kwh": _r(r.expected_reported_kwh, 2),
                        "reported_hardware_kwh": r.reported_capacity_kwh},
)

WORST_MODULE_SENSOR = _pct(
    "most_used_module_throughput", "mdi:battery-alert-variant-outline", lambda r: r.worst_module_pct,
    lambda r: {"worst_module": r.worst_module_id, "modules": r.module_details,
               "module_total_vs_plant_pct": _r(r.module_vs_plant_pct, 1)})

SOC_SPREAD_SENSOR = _pct(
    "module_soc_spread", "mdi:battery-sync-outline", lambda r: _r(r.soc_spread, 1),
    lambda r: {"module_soc": r.module_soc}, precision=1)

HEALTH_MARGIN_SENSOR = _pct(
    "soh_above_warranty_floor", "mdi:battery-plus-variant", lambda r: _r(r.health_margin, 1),
    lambda r: {"reported_soh_pct": r.reported_soh_pct, "warranty_floor_pct": _r(r.floor_pct, 1)}, precision=1)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: LedgerRuntime = entry.runtime_data
    descriptions = list(SENSORS)
    if runtime.config.get(CONF_CAPACITY_ENTITY):
        descriptions.append(HARDWARE_SENSOR)
    if runtime.config.get(CONF_SOH_ENTITY):
        descriptions.append(HEALTH_MARGIN_SENSOR)
    if runtime.modules:
        descriptions.append(WORST_MODULE_SENSOR)
    if sum(1 for m in runtime.modules if m.get(MOD_SOC)) > 1:
        descriptions.append(SOC_SPREAD_SENSOR)
    async_add_entities(LedgerSensor(runtime, d) for d in descriptions)


class LedgerSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    # Keep bulky / fast-changing detail out of the recorder database.
    _unrecorded_attributes = frozenset({
        "groups", "notes", "average_daily_kwh", "low_confidence",
        "remaining_value_by_warranty_life", "expected_reported_kwh",
        "modules", "module_soc", "worst_module", "module_total_vs_plant_pct",
        "reported_soh_pct", "warranty_floor_pct",
        # Kept for the original YAML package's dashboards; each is also its own sensor.
        "percent_of_rated_life_used", "estimated_remaining_value", "remaining_usable_kwh",
        "degradation_driver", "warranty_status",
    })
    entity_description: LedgerSensorDescription

    def __init__(self, runtime: LedgerRuntime, description: LedgerSensorDescription) -> None:
        self.runtime = runtime
        self.entity_description = description
        entry = runtime.entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # sensor.battery_ledger_<key>; Home Assistant adds _2, _3 ... if a second setup needs the same ID.
        self.entity_id = f"sensor.{ENTITY_ID_PREFIX}_{description.key}"
        specs = [g[CONF_SPEC] for g in runtime.groups]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=", ".join(dict.fromkeys(s["brand"] for s in specs)),
            model=", ".join(dict.fromkeys(s["model"] for s in specs)),
            entry_type=DeviceEntryType.SERVICE,
        )
        if description.unit_fn:
            self._attr_native_unit_of_measurement = description.unit_fn(runtime.currency)
        self._attr_attribution = f"Specs: {NAME} Store"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self.runtime.signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        res = self.runtime.result
        return res is not None and self.entity_description.value_fn(res) is not None

    @property
    def native_value(self):
        res = self.runtime.result
        return None if res is None else self.entity_description.value_fn(res)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        res = self.runtime.result
        if res is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(res)
