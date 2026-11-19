"""Per-entry runtime: reads the source sensors and recalculates the ledger."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfEnergy
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .const import (
    CONF_CAPACITY_ENTITY,
    CONF_CHARGED_ENTITY,
    CONF_COST,
    CONF_CURRENCY,
    CONF_CURRENCY_STYLE,
    CURRENCY_STYLE_SYMBOL,
    CURRENCY_SYMBOLS,
    CONF_DISCHARGED_ENTITY,
    CONF_GROUPS,
    CONF_INSTALL_DATE,
    CONF_MODULES,
    CONF_SOH_ENTITY,
    CONF_SPEC,
    CONF_UNITS,
    MOD_DISCHARGED,
    MOD_GROUP,
    MOD_ID,
    MOD_SOC,
    RECALC_DEBOUNCE_SECONDS,
    RECALC_INTERVAL,
    SIGNAL_UPDATE,
    STARTUP_WAIT,
)
from .ledger import GroupInput, LedgerInput, LedgerResult, SpecError, compute

_LOGGER = logging.getLogger(__name__)


def entry_config(entry: ConfigEntry) -> dict[str, Any]:
    """Setup data with any options-flow overrides applied."""
    return {**entry.data, **entry.options}


class LedgerRuntime:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.result: LedgerResult | None = None
        self.problem: str | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._pending: CALLBACK_TYPE | None = None
        # Startup: no calculation until every configured source has reported (or STARTUP_WAIT
        # after Home Assistant started), so a source that's still connecting isn't mistaken for
        # one that isn't configured. Until then the sensors are unavailable.
        self.ready = False
        self._wait_timer: CALLBACK_TYPE | None = None
        # Last valid reading of each source (kWh for energy counters), used while a configured
        # source is briefly unavailable so the basis or module tracking doesn't flip.
        self._last: dict[str, float] = {}

    @property
    def config(self) -> dict[str, Any]:
        return entry_config(self.entry)

    @property
    def currency(self) -> str:
        """ISO currency code: Home Assistant's regional setting (or a pre-1.3 entry's own)."""
        return self.config.get(CONF_CURRENCY) or self.hass.config.currency

    @property
    def currency_label(self) -> str:
        """For the cost-per-kWh unit: the code, or its symbol if the user chose symbols."""
        if self.config.get(CONF_CURRENCY_STYLE) == CURRENCY_STYLE_SYMBOL:
            return CURRENCY_SYMBOLS.get(self.currency, self.currency)
        return self.currency

    @property
    def groups(self) -> list[dict]:
        return self.config[CONF_GROUPS]

    @property
    def signal(self) -> str:
        return SIGNAL_UPDATE.format(entry_id=self.entry.entry_id)

    @property
    def modules(self) -> list[dict]:
        return self.config.get(CONF_MODULES) or []

    def _watched(self) -> list[str]:
        cfg = self.config
        ids = [cfg.get(k) for k in (CONF_CHARGED_ENTITY, CONF_DISCHARGED_ENTITY,
                                     CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY)]
        for m in self.modules:
            ids += [m.get(MOD_DISCHARGED), m.get(MOD_SOC)]
        return [e for e in ids if e]

    @callback
    def async_start(self) -> None:
        self._unsubs.append(async_track_state_change_event(self.hass, self._watched(), self._on_state))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, RECALC_INTERVAL))
        if self._sources_ready():
            self._set_ready()
        else:
            self._unsubs.append(async_at_started(self.hass, self._on_started))

    @callback
    def async_stop(self) -> None:
        for cancel in (self._pending, self._wait_timer):
            if cancel:
                cancel()
        self._pending = self._wait_timer = None
        while self._unsubs:
            self._unsubs.pop()()

    @staticmethod
    def _valid(state: State | None) -> bool:
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN, "")

    def _missing(self) -> list[str]:
        return [e for e in self._watched() if not self._valid(self.hass.states.get(e))]

    def _sources_ready(self) -> bool:
        return not self._missing()

    @callback
    def _on_started(self, _hass: HomeAssistant) -> None:
        if not self.ready:
            self._wait_timer = async_call_later(self.hass, STARTUP_WAIT, self._on_wait_timeout)

    @callback
    def _on_wait_timeout(self, _now) -> None:
        self._wait_timer = None
        if not self.ready:
            _LOGGER.info("BatteryLedger '%s': still no reading from %s; calculating without it",
                         self.entry.title, ", ".join(self._missing()))
            self._set_ready()

    @callback
    def _set_ready(self) -> None:
        self.ready = True
        if self._wait_timer:
            self._wait_timer()
            self._wait_timer = None
        self.recalculate()

    @callback
    def _on_state(self, event: Event) -> None:
        if not self.ready:
            if self._sources_ready():
                self._set_ready()
            return
        # Energy counters can update every few seconds; batch recalculations.
        if self._pending is None:
            self._pending = async_call_later(self.hass, RECALC_DEBOUNCE_SECONDS, self._run_pending)

    @callback
    def _run_pending(self, _now) -> None:
        self._pending = None
        self.recalculate()

    @callback
    def _on_tick(self, _now) -> None:
        self.recalculate()

    def _read_number(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if self._valid(state):
            try:
                self._last[entity_id] = float(state.state)
            except ValueError:
                pass
        return self._last.get(entity_id)

    def _read_kwh(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        key = f"{entity_id}|kWh"
        if self._valid(state):
            try:
                value = float(state.state)
            except ValueError:
                value = None
            if value is not None:
                unit = state.attributes.get("unit_of_measurement") or UnitOfEnergy.KILO_WATT_HOUR
                if unit == UnitOfEnergy.KILO_WATT_HOUR:
                    self._last[key] = value
                elif unit in EnergyConverter.VALID_UNITS:
                    self._last[key] = EnergyConverter.convert(value, unit, UnitOfEnergy.KILO_WATT_HOUR)
                else:
                    _LOGGER.warning("%s has unit '%s', which isn't an energy unit; ignoring it", entity_id, unit)
                    self._last.pop(key, None)
        return self._last.get(key)

    @callback
    def recalculate(self) -> None:
        if not self.ready:
            return
        cfg = self.config
        charged = self._read_kwh(cfg.get(CONF_CHARGED_ENTITY))
        discharged = self._read_kwh(cfg.get(CONF_DISCHARGED_ENTITY))
        capacity = self._read_kwh(cfg.get(CONF_CAPACITY_ENTITY))
        soh = self._read_number(cfg.get(CONF_SOH_ENTITY))
        if soh is not None and soh <= 0:
            soh = None  # 0% is a source that doesn't report SoH (e.g. publishing 0), not a dead battery

        module_kwh: dict[int, dict[str, float]] = {}
        module_soc: dict[str, float] = {}
        for m in self.modules:
            kwh = self._read_kwh(m.get(MOD_DISCHARGED))
            if kwh is not None:
                module_kwh.setdefault(int(m[MOD_GROUP]), {})[m[MOD_ID]] = kwh
            soc = self._read_number(m.get(MOD_SOC))
            if soc is not None:
                module_soc[m[MOD_ID]] = soc

        try:
            self.result = compute(LedgerInput(
                groups=[GroupInput(g[CONF_SPEC], int(g[CONF_UNITS]), date.fromisoformat(g[CONF_INSTALL_DATE]),
                                   module_kwh=module_kwh.get(i), cost=g.get(CONF_COST))
                        for i, g in enumerate(self.groups)],
                today=dt_util.now().date(),
                charged_kwh=charged,
                discharged_kwh=discharged,
                reported_capacity_kwh=capacity,
                reported_soh_pct=soh,
                module_soc=module_soc,
            ))
            self.problem = None
        except (SpecError, KeyError, ValueError) as err:
            self.result = None
            self.problem = str(err)
            _LOGGER.debug("BatteryLedger '%s' can't calculate: %s", self.entry.title, err)
        async_dispatcher_send(self.hass, self.signal)
