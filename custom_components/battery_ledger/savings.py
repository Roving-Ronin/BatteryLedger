"""Savings for return on investment, kept per day.

Whole installation: Home Energy Advisor (HEA) works the installation's saving out on request with its
`compare_plans` action, never as a sensor (its ADR-0047: the figure is recomputed from inputs the household can
correct). For a period, the saving is the chosen plan's `without_installation` (everything the house used, bought
from the grid on the plan it would be on without solar or battery) less the current plan's `total`. Days are asked
for one at a time: backfilled newest first in the background, the last LOOK_BACK_DAYS redone nightly, today every
TODAY_EVERY,
and every Monday each finished month is checked with one call against the sum of its days and redone if it differs.

Battery only: a running-total savings sensor (HEA's Battery Savings). Its value is the total; it's noted once a
day, so each day's saving is the difference to the next.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    HEA_COMPARE,
    HEA_DOMAIN,
    ROI_BEFORE,
    ROI_MODE,
    ROI_MODE_INSTALLATION,
    ROI_OTHER_COSTS,
    ROI_PLAN,
    ROI_START,
)
from .ledger import RoiInput

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
SAVE_DELAY = 30
LOOK_BACK_DAYS = 35  # late data and Repairs land in the last month or so
CALL_PAUSE = 2.0  # seconds between calls, so a backfill doesn't load Home Assistant
TODAY_EVERY = timedelta(minutes=15)  # how often today so far is asked for
MONTH_TOLERANCE = 0.05  # a month that differs from its days by more than this is redone

# Why there are no (new) figures: shown as the savings sensor's status
STATUS_OK = "ok"
STATUS_BACKFILLING = "backfilling"
STATUS_NO_HEA = "hea_not_available"  # Home Energy Advisor isn't installed, loaded or answering
STATUS_NO_PLAN = "plan_not_found"  # the chosen plan isn't in Home Energy Advisor any more
STATUS_NO_DAILY_CHARGE = "daily_charge_missing"  # HEA's current plan has no daily charge yet
STATUS_NO_SENSOR = "no_savings_sensor"


def store_key(entry_id: str) -> str:
    return f"{DOMAIN}.savings.{entry_id}"


def installation_saving(answer: dict[str, Any], plan_id: str) -> tuple[float | None, str]:
    """The saving in one `compare_plans` answer, and a status: the chosen plan's cost without the installation
    less the current plan's actual total."""
    plans = {p.get("id"): p for p in answer.get("plans") or []}
    current = next((p for p in plans.values() if p.get("current")), None)
    chosen = plans.get(plan_id)
    if chosen is None:
        return None, STATUS_NO_PLAN
    if current is None or current.get("daily_charge_missing"):
        return None, STATUS_NO_DAILY_CHARGE
    without, total = chosen.get("without_installation"), current.get("total")
    if not isinstance(without, int | float) or not isinstance(total, int | float):
        return None, STATUS_OK  # nothing to price that day (no data, no price): left out
    return round(float(without) - float(total), 4), STATUS_OK


class SavingsTracker:
    def __init__(self, hass: HomeAssistant, entry_id: str, roi: dict[str, Any], first_install: date,
                 on_change: Callable[[], None]) -> None:
        self.hass = hass
        self.roi = roi
        self.whole = roi.get(ROI_MODE) == ROI_MODE_INSTALLATION
        self.start = date.fromisoformat(roi[ROI_START]) if roi.get(ROI_START) else first_install
        self._on_change = on_change
        self._store: Store = Store(hass, STORE_VERSION, store_key(entry_id))
        self.days: dict[date, float] = {}
        self.snapshots: dict[date, float] = {}  # battery only: the sensor's value when first seen each day
        self.total: float = 0.0  # battery only: the sensor's value
        self.status = STATUS_OK
        self.calculated: datetime | None = None
        self._queue: list[date | tuple[int, int]] = []  # days, and (year, month) checks
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._unsubs: list[Callable[[], None]] = []

    # --- storage -------------------------------------------------------------------------------------------
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        if self.whole and data.get(ROI_PLAN) != self.roi.get(ROI_PLAN):
            data = {}  # another plan chosen: everything is worked out again
        self.days = {date.fromisoformat(k): float(v) for k, v in (data.get("days") or {}).items()}
        self.snapshots = {date.fromisoformat(k): float(v) for k, v in (data.get("snapshots") or {}).items()}

    def _data(self) -> dict[str, Any]:
        return {ROI_PLAN: self.roi.get(ROI_PLAN),
                "days": {d.isoformat(): v for d, v in sorted(self.days.items())},
                "snapshots": {d.isoformat(): v for d, v in sorted(self.snapshots.items())}}

    def _save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_flush(self) -> None:
        await self._store.async_save(self._data())

    # --- what the ledger needs ------------------------------------------------------------------------------
    def roi_input(self) -> RoiInput:
        total = sum(self.days.values()) if self.whole else self.total
        return RoiInput(total=total, days=dict(self.days), before=float(self.roi.get(ROI_BEFORE) or 0),
                        other_costs=float(self.roi.get(ROI_OTHER_COSTS) or 0) if self.whole else 0.0,
                        start=self.start)

    # --- battery only ---------------------------------------------------------------------------------------
    @callback
    def observe(self, value: float | None, today: date) -> None:
        """The savings sensor's value: noted once a day; each day's saving is the difference to the next day's."""
        if self.whole:
            return
        if value is None:
            self.status = STATUS_NO_SENSOR
            return
        self.status, self.total = STATUS_OK, value
        if today not in self.snapshots:
            self.snapshots[today] = value
            self._save()
        noted = sorted(self.snapshots)
        self.days = {d: round(self.snapshots[n] - self.snapshots[d], 4) for d, n in zip(noted, noted[1:], strict=False)}
        self.days[today] = round(value - self.snapshots[today], 4)

    # --- whole installation: asking Home Energy Advisor -----------------------------------------------------
    @callback
    def async_start(self) -> None:
        if not self.whole:
            return
        today = dt_util.now().date()
        missing = [self.start + timedelta(days=n) for n in range((today - self.start).days)]
        self._enqueue([today] + sorted((d for d in missing if d not in self.days), reverse=True))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_today, TODAY_EVERY))
        self._unsubs.append(async_track_time_change(self.hass, self._on_night, hour=1, minute=17, second=0))
        self._task = self.hass.async_create_background_task(self._worker(), f"{DOMAIN} savings")

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        if self._task:
            self._task.cancel()
            self._task = None

    def _enqueue(self, items: list) -> None:
        self._queue.extend(i for i in items if i not in self._queue)
        self._wake.set()

    @callback
    def _on_today(self, _now: datetime) -> None:
        self._enqueue([dt_util.now().date()])

    @callback
    def _on_night(self, now: datetime) -> None:
        today = dt_util.as_local(now).date()
        recent = [today - timedelta(days=n) for n in range(1, LOOK_BACK_DAYS + 1)]
        self._enqueue([d for d in recent if d >= self.start])
        if today.weekday() == 0:  # Mondays: each finished month, one call each
            months = sorted({(d.year, d.month) for d in self.days if (d.year, d.month) != (today.year, today.month)})
            self._enqueue(months)

    async def _ask(self, start: datetime, end: datetime) -> dict[str, Any] | None:
        try:
            answer = await self.hass.services.async_call(
                HEA_DOMAIN, HEA_COMPARE, {"start": start, "end": end}, blocking=True, return_response=True)
        except ServiceNotFound:
            self.status = STATUS_NO_HEA
            return None
        except HomeAssistantError as err:  # e.g. HEA not loaded, or a period it can't answer
            _LOGGER.debug("Home Energy Advisor couldn't compare %s to %s: %s", start, end, err)
            if getattr(err, "translation_key", None) == "compare_not_loaded":
                self.status = STATUS_NO_HEA
            return None
        return answer if isinstance(answer, dict) else None

    async def _day(self, day: date) -> None:
        start = dt_util.start_of_local_day(day)
        end = min(start + timedelta(days=1), dt_util.now())
        if end - start < timedelta(minutes=5):
            return
        answer = await self._ask(start, end)
        if answer is None:
            return
        saving, status = installation_saving(answer, self.roi.get(ROI_PLAN))
        self.status = status
        if status != STATUS_OK:
            return
        if not answer.get("days"):
            saving = None  # no recorded data for the day (e.g. before Home Assistant's statistics): not a $0 day
        if saving is None:
            self.days.pop(day, None)
        else:
            self.days[day] = saving
        self.calculated = dt_util.utcnow()
        self._save()

    async def _month(self, year: int, month: int) -> None:
        first = date(year, month, 1)
        nxt = date(year + month // 12, month % 12 + 1, 1)
        answer = await self._ask(dt_util.start_of_local_day(first), dt_util.start_of_local_day(nxt))
        if answer is None:
            return
        saving, status = installation_saving(answer, self.roi.get(ROI_PLAN))
        if status != STATUS_OK or saving is None:
            return
        days = [d for d in self.days if first <= d < nxt]
        if abs(sum(self.days[d] for d in days) - saving) > MONTH_TOLERANCE:
            self._enqueue([first + timedelta(days=n) for n in range((nxt - first).days) if first + timedelta(days=n) >= self.start])

    async def _worker(self) -> None:
        while True:
            if not self._queue:
                if self.status == STATUS_BACKFILLING:
                    self.status = STATUS_OK
                self._on_change()
                self._wake.clear()
                await self._wake.wait()
                continue
            item = self._queue.pop(0)
            if len(self._queue) > 1 and self.status == STATUS_OK:
                self.status = STATUS_BACKFILLING
            if isinstance(item, tuple):
                await self._month(*item)
            else:
                await self._day(item)
            if self.status in (STATUS_NO_HEA, STATUS_NO_PLAN, STATUS_NO_DAILY_CHARGE):
                self._queue.clear()  # tried again on the next hour / night
            if len(self.days) % 10 == 0 or not self._queue:
                self._on_change()
            if self._queue:
                await asyncio.sleep(CALL_PAUSE)
