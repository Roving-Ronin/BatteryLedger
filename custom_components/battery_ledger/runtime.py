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
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .capacity import CapacityLearner, combine
from .savings import SavingsTracker
from .const import (
    CONF_CAPACITY_ENTITY,
    CONF_CHARGED_ENTITY,
    CONF_COST,
    CONF_CURRENCY,
    CONF_CURRENCY_STYLE,
    CURRENCY_STYLE_SYMBOL,
    CURRENCY_SYMBOLS,
    CONF_DISCHARGED_ENTITY,
    CONF_ESL_YEARS,
    CONF_EXPORT_SETTING,
    CONF_GROUPS,
    LIVE_OPTIONS,
    CONF_INSTALL_DATE,
    CONF_MODULES,
    CONF_PACK_SOH,
    CONF_ROI,
    CONF_SOC_ENTITY,
    CONF_TOWERS,
    ROI_SAVINGS_ENTITY,
    TOWER_CHARGED,
    TOWER_DISCHARGED,
    TOWER_GROUP,
    TOWER_SOC,
    DOMAIN,
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
from .ledger import EXPORT_WARRANTY, GroupInput, LedgerInput, LedgerResult, SpecError, compute

_LOGGER = logging.getLogger(__name__)


def entry_config(entry: ConfigEntry) -> dict[str, Any]:
    """Setup data with any options-flow overrides applied."""
    return {**entry.data, **entry.options}


CAPACITY_STORE_VERSION = 1
CAPACITY_SAVE_DELAY = 60  # seconds


def capacity_store_key(entry_id: str) -> str:
    return f"{DOMAIN}.capacity.{entry_id}"


class LedgerRuntime:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.result: LedgerResult | None = None
        self.problem: str | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._pending: CALLBACK_TYPE | None = None
        self._seen: tuple[dict, dict] = ({}, {})
        self.remember_entry()
        # Startup: no calculation until every configured source has reported (or STARTUP_WAIT
        # after Home Assistant started), so a source that's still connecting isn't mistaken for
        # one that isn't configured. Until then the sensors are unavailable.
        self.ready = False
        self._wait_timer: CALLBACK_TYPE | None = None
        # Last valid reading of each source (kWh for energy counters), used while a configured
        # source is briefly unavailable so the basis or module tracking doesn't flip.
        self._last: dict[str, float] = {}
        # Measured usable capacity, learned from state-of-charge runs (only with a SoC sensor)
        self.learner: CapacityLearner | None = None
        self._learner_soc: str | None = None  # the SoC sensor it learned from
        # With battery towers: one learner per tower instead, each kept by its tower's SoC sensor
        self.tower_learners: list[CapacityLearner] = []
        # Savings for return on investment (Configure → ROI), when set up
        self.savings: SavingsTracker | None = None
        self._capacity_store: Store = Store(hass, CAPACITY_STORE_VERSION, capacity_store_key(entry.entry_id))

    @property
    def towers(self) -> list[dict]:
        return self.config.get(CONF_TOWERS) or []

    async def async_load(self) -> None:
        """Load the savings kept for ROI, and what the capacity learners have recorded."""
        if roi := self.config.get(CONF_ROI):
            self.savings = SavingsTracker(
                self.hass, self.entry.entry_id, roi,
                min(date.fromisoformat(g[CONF_INSTALL_DATE]) for g in self.groups), self._savings_changed)
            await self.savings.async_load()
        await self._async_load_capacity()

    @callback
    def _savings_changed(self) -> None:
        if self.ready and self._pending is None:
            self._pending = async_call_later(self.hass, RECALC_DEBOUNCE_SECONDS, self._run_pending)

    async def _async_load_capacity(self) -> None:
        """Load what the capacity learners have recorded. Towers, if set up, are measured instead of the whole
        battery's SoC sensor; each learner starts again when its SoC sensor changes."""
        towers = self.towers
        soc_entity = self.config.get(CONF_SOC_ENTITY)
        if not towers and not soc_entity:
            return
        data = await self._capacity_store.async_load() or {}
        if towers:
            saved = data.get("towers") if isinstance(data.get("towers"), dict) else {}
            self.tower_learners = [CapacityLearner(saved.get(t[TOWER_SOC])) for t in towers]
            return
        self._learner_soc = soc_entity
        self.learner = CapacityLearner(data.get("learner") if data.get("soc_entity") == soc_entity else None)

    @property
    def measuring(self) -> bool:
        return self.learner is not None or bool(self.tower_learners)

    def _capacity_data(self) -> dict[str, Any]:
        if self.tower_learners:
            return {"towers": {t[TOWER_SOC]: dict(lr.state)
                               for t, lr in zip(self.towers, self.tower_learners, strict=True)}}
        return {"soc_entity": self._learner_soc, "learner": dict(self.learner.state)}

    def _save_capacity(self) -> None:
        data = self._capacity_data()
        self._capacity_store.async_delay_save(lambda: data, CAPACITY_SAVE_DELAY)

    async def async_save_capacity(self) -> None:
        """On unload: write now, so a reload doesn't lose a run recorded (or a day's savings) since the last save."""
        if self.savings is not None:
            await self.savings.async_flush()
        if self.measuring:
            await self._capacity_store.async_save(self._capacity_data())

    def remember_entry(self) -> None:
        self._seen = (dict(self.entry.data), dict(self.entry.options))

    def only_live_options_changed(self) -> bool:
        """The entry changed only in options that apply without a reload (LIVE_OPTIONS)."""
        data, options = self._seen

        def strip(o: dict) -> dict:
            return {k: v for k, v in o.items() if k not in LIVE_OPTIONS}

        return dict(self.entry.data) == data and strip(dict(self.entry.options)) == strip(options)

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
                                     CONF_CAPACITY_ENTITY, CONF_SOH_ENTITY, CONF_SOC_ENTITY)]
        ids += list(cfg.get(CONF_PACK_SOH) or [])
        for t in cfg.get(CONF_TOWERS) or []:
            ids += [t.get(TOWER_SOC), t.get(TOWER_CHARGED), t.get(TOWER_DISCHARGED)]
        for m in self.modules:
            ids += [m.get(MOD_DISCHARGED), m.get(MOD_SOC)]
        ids.append((cfg.get(CONF_ROI) or {}).get(ROI_SAVINGS_ENTITY))
        return [e for e in ids if e]

    @callback
    def async_start(self) -> None:
        if self.savings is not None:
            self.savings.async_start()
            self._unsubs.append(self.savings.async_stop)
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

    def _roi_input(self):
        if self.savings is None:
            return None
        entity = self.config[CONF_ROI].get(ROI_SAVINGS_ENTITY)
        if entity:  # battery only: a running-total savings sensor
            self.savings.observe(self._read_number(entity), dt_util.now().date())
        return self.savings.roi_input()

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
        if soh is None and cfg.get(CONF_PACK_SOH):
            # No whole-battery SoH: the average of the packs that report one
            packs = [v for e in cfg[CONF_PACK_SOH] if (v := self._read_number(e)) is not None and v > 0]
            soh = sum(packs) / len(packs) if packs else None

        module_kwh: dict[int, dict[str, float]] = {}
        module_soc: dict[str, float] = {}
        for m in self.modules:
            kwh = self._read_kwh(m.get(MOD_DISCHARGED))
            if kwh is not None:
                module_kwh.setdefault(int(m[MOD_GROUP]), {})[m[MOD_ID]] = kwh
            soc = self._read_number(m.get(MOD_SOC))
            if soc is not None:
                module_soc[m[MOD_ID]] = soc

        tower_measured = []
        if self.tower_learners:
            recorded = False
            for t, learner in zip(self.towers, self.tower_learners, strict=True):
                if self._valid(self.hass.states.get(t[TOWER_SOC])):  # a fresh reading only, as below
                    recorded |= learner.observe(self._read_number(t[TOWER_SOC]), self._read_kwh(t.get(TOWER_CHARGED)),
                                                self._read_kwh(t.get(TOWER_DISCHARGED)))
                tower_measured.append((int(t.get(TOWER_GROUP, 0)), learner.measured()))
            if recorded:
                self._save_capacity()
        if self.learner is not None:
            # Only a fresh SoC reading: a remembered one beside new energy figures would invent a run
            soc_state = self.hass.states.get(self._learner_soc)
            if self._valid(soc_state):
                if self.learner.observe(self._read_number(self._learner_soc), charged, discharged):
                    self._save_capacity()  # once per recorded run: a run in progress starts again after a restart

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
                esl_years=self.config.get(CONF_ESL_YEARS),
                export_setting=self.config.get(CONF_EXPORT_SETTING) or EXPORT_WARRANTY,
                measured=combine([m for _g, m in tower_measured]) if tower_measured
                else self.learner.measured() if self.learner is not None else None,
                tower_measured=tower_measured,
                roi=self._roi_input(),
            ))
            self.problem = None
        except (SpecError, KeyError, ValueError) as err:
            self.result = None
            self.problem = str(err)
            _LOGGER.debug("BatteryLedger '%s' can't calculate: %s", self.entry.title, err)
        async_dispatcher_send(self.hass, self.signal)
