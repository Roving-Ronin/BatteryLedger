"""Return on investment: Configure → ROI, the savings tracker (Home Energy Advisor's compare_plans action, or a
savings sensor) and the four ROI sensors, against a real test Home Assistant."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.battery_ledger import savings
from custom_components.battery_ledger.const import CONFIG_ENTRY_MINOR_VERSION, CONFIG_ENTRY_VERSION, DOMAIN
from custom_components.battery_ledger.store_client import async_get_store_index

CHARGED = "sensor.charged"
PER_DAY = 5.0  # what the fake Home Energy Advisor saves a day: Red Energy 5.50 without the installation, Covau 0.50


def _fake_hea(hass: HomeAssistant, per_day=PER_DAY, daily_charge_missing=False, calls=None, priced_from=None):
    async def compare(call: ServiceCall):
        start, end = call.data["start"], call.data["end"]
        days = (end - start).total_seconds() / 86400
        if calls is not None:
            calls.append((start, end))
        rate = per_day(start) if callable(per_day) else per_day
        priced = priced_from is None or start.date() >= priced_from
        current = ({"total": round(0.5 * days, 4)} if priced
                   else {"no_price": True, "no_price_entities": ["sensor.grid_buy_price"]})
        return {"days": days, "hours": int(days * 24), "left_out": [], "plans": [
            {"id": "covau", "name": "Covau", "current": True, **current,
             **({"daily_charge_missing": True} if daily_charge_missing else {})},
            {"id": "red", "name": "Red Energy", "current": False, "total": round(9 * days, 4),
             "without_installation": round((0.5 + rate) * days, 4)},
            {"id": "amber", "name": "Amber Energy", "current": False, "total": 1.0,
             "without_installation": 1.0}]}

    hass.services.async_register("home_energy_advisor", "compare_plans", compare,
                                 supports_response=SupportsResponse.ONLY)


async def _entry(hass: HomeAssistant, days_ago=20, roi=None, cost=20000.0):
    index = await async_get_store_index(hass)
    spec = index.get("sigenergy-sigenstor-bat-8-0-anz")
    install = (dt_util.now().date() - timedelta(days=days_ago)).isoformat()
    hass.states.async_set(CHARGED, "300", {"unit_of_measurement": "kWh"})
    data = {"name": "Home", "groups": [{"spec": spec, "units": 4, "install_date": install, "cost": cost}],
            "charged_energy_entity": CHARGED}
    if roi:
        data["roi"] = roi
    entry = MockConfigEntry(domain=DOMAIN, title="Home", version=CONFIG_ENTRY_VERSION,
                            minor_version=CONFIG_ENTRY_MINOR_VERSION, data=data)
    entry.add_to_hass(hass)
    return entry


async def _settle(hass: HomeAssistant, entry):
    """Let the tracker's background worker finish its queue, then recalculate."""
    tracker = entry.runtime_data.savings
    for _ in range(200):
        await hass.async_block_till_done()
        if not tracker._queue:
            break
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def _no_pause():
    with patch.object(savings, "CALL_PAUSE", 0):
        yield


async def test_whole_installation_from_home_energy_advisor(hass: HomeAssistant, hass_storage):
    """Configure → ROI → Whole installation → the plan without solar or battery; the tracker asks HEA for each
    day since install; savings, ROI, break-even and projected lifetime savings follow."""
    _fake_hea(hass)
    entry = await _entry(hass, days_ago=20)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert "roi" in r["menu_options"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "roi"})
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"mode": "installation", "before": 100, "other_costs": 10000})
    assert r["step_id"] == "roi_plan"
    plan_key = next(k for k in r["data_schema"].schema if str(k) == "plan_id")
    options = [o["value"] for o in r["data_schema"].schema[plan_key].config["options"]]
    assert options == ["red", "amber"]  # the current plan (Covau) isn't offered
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"plan_id": "red"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data["roi"]["plan_name"] == "Red Energy"
    await _settle(hass, entry)

    today = dt_util.now().date()
    tracker = entry.runtime_data.savings
    # Each day since install (20) at $5, and today so far (part of a day)
    assert len([d for d in tracker.days if d < today]) == 20
    assert all(tracker.days[d] == pytest.approx(PER_DAY) for d in tracker.days if d < today)
    savings_state = hass.states.get("sensor.battery_ledger_savings_to_date")
    expected = sum(tracker.days.values()) + 100
    assert float(savings_state.state) == pytest.approx(expected, abs=0.01)
    a = savings_state.attributes
    assert a["plan_without"] == "Red Energy" and a["before_figures"] == 100 and a["status"] == "ok"
    assert a["days_counted"] == 21 and a["days_since_install"] == 21
    roi = hass.states.get("sensor.battery_ledger_return_on_investment")
    assert roi.attributes["investment"] == 30000  # $20,000 batteries + $10,000 other system costs
    assert float(roi.state) == pytest.approx((expected - 30000) / 30000 * 100, abs=0.1)
    be = hass.states.get("sensor.battery_ledger_break_even_date")
    assert be.attributes["confidence"] == "low" and be.state > today.isoformat()
    life = hass.states.get("sensor.battery_ledger_projected_lifetime_savings")
    assert float(life.state) > expected and life.attributes["per_year"] is not None

    # Kept across a reload, and not asked again
    calls: list = []
    hass.services.async_remove("home_energy_advisor", "compare_plans")
    _fake_hea(hass, calls=calls)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await _settle(hass, entry)
    assert len(calls) == 1  # only today
    assert hass_storage[f"{DOMAIN}.savings.{entry.entry_id}"]["data"]["plan_id"] == "red"

    # Off: the sensors go, and the stored savings with the setup
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "roi"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"mode": "off"})
    await hass.async_block_till_done()
    assert entry.data["roi"] == {"mode": "off"}  # kept as a choice, so the Repairs notice doesn't return
    assert hass.states.get("sensor.battery_ledger_savings_to_date").state == "unavailable"


async def test_months_checked_and_redone(hass: HomeAssistant):
    """Monday nights each finished month is asked for in one call; a month that no longer matches its days (a
    price corrected in HEA) has its days asked for again."""
    today = dt_util.now().date()
    rate = {"v": PER_DAY}
    _fake_hea(hass, per_day=lambda _start: rate["v"])
    entry = await _entry(hass, days_ago=70, roi={"mode": "installation", "plan_id": "red", "plan_name": "Red"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass, entry)
    tracker = entry.runtime_data.savings
    first = min(tracker.days)
    assert tracker.days[first] == pytest.approx(PER_DAY)

    rate["v"] = 7.0  # the plan's prices corrected in Home Energy Advisor
    monday = dt_util.start_of_local_day(today - timedelta(days=today.weekday()))
    tracker._on_night(monday)
    await _settle(hass, entry)
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    assert tracker.days[last_month] == pytest.approx(7.0)  # a finished month: redone
    assert tracker.days[first] == pytest.approx(7.0)


async def test_home_energy_advisor_missing_or_not_ready(hass: HomeAssistant):
    entry = await _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "roi"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"mode": "installation"})
    assert r["step_id"] == "roi" and r["errors"] == {"base": "hea_not_available"}

    # Set up, but HEA's current plan has no daily charge yet: no days counted, and the status says why
    _fake_hea(hass, daily_charge_missing=True)
    entry2 = await _entry(hass, roi={"mode": "installation", "plan_id": "red", "plan_name": "Red"})
    assert await hass.config_entries.async_setup(entry2.entry_id)
    await _settle(hass, entry2)
    assert entry2.runtime_data.savings.days == {}
    st = [s for s in hass.states.async_all("sensor") if s.entity_id.startswith("sensor.battery_ledger_savings_to_date")]
    assert any(s.attributes.get("status") == "daily_charge_missing" for s in st)


async def test_backfill_waits_for_home_energy_advisor(hass: HomeAssistant):
    """HEA not loaded yet when BatteryLedger starts (e.g. after a restart): the past days are kept, and asked for
    once today's next ask is answered, not dropped until the next restart."""
    entry = await _entry(hass, days_ago=20, roi={"mode": "installation", "plan_id": "red", "plan_name": "Red"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass, entry)
    tracker = entry.runtime_data.savings
    assert tracker.days == {} and tracker.status == savings.STATUS_NO_HEA

    _fake_hea(hass)
    tracker._on_today(dt_util.now())
    await _settle(hass, entry)
    today = dt_util.now().date()
    assert len([d for d in tracker.days if d < today]) == 20
    assert tracker.status == "ok"


async def test_retries_every_30_seconds_until_hea_answers(hass: HomeAssistant):
    """After a restart HEA can take minutes to answer: asked again every 30 seconds (not the next 15-minute ask),
    and the past days follow once it does."""
    entry = await _entry(hass, days_ago=5, roi={"mode": "installation", "plan_id": "red", "plan_name": "Red"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass, entry)
    tracker = entry.runtime_data.savings
    assert tracker.status == savings.STATUS_NO_HEA

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))  # still not there: tried again
    await _settle(hass, entry)
    assert tracker.status == savings.STATUS_NO_HEA and tracker._retry is not None

    _fake_hea(hass)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=62))
    await _settle(hass, entry)
    assert tracker.status == "ok" and len(tracker.days) == 6 and tracker._retry is None


async def test_days_the_current_plan_isnt_priced(hass: HomeAssistant):
    """HEA can't price its current plan before its price sensors had statistics: those days are left out (not $0),
    and the status and days_not_priced say so."""
    today = dt_util.now().date()
    _fake_hea(hass, priced_from=today - timedelta(days=2))
    entry = await _entry(hass, days_ago=10, roi={"mode": "installation", "plan_id": "red", "plan_name": "Red"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass, entry)
    tracker = entry.runtime_data.savings
    assert sorted(d for d in tracker.days if d < today) == [today - timedelta(days=2), today - timedelta(days=1)]
    assert len(tracker.not_priced) == 8
    state = hass.states.get("sensor.battery_ledger_savings_to_date")
    assert state.attributes["status"] == savings.STATUS_NOT_PRICED
    assert state.attributes["days_not_priced"] == 8


async def test_battery_only_from_a_savings_sensor(hass: HomeAssistant):
    """Battery only: the sensor's value is the total; noted once a day, so each day's saving is the difference."""
    hass.states.async_set("sensor.battery_savings", "812.40", {"unit_of_measurement": "AUD"})
    entry = await _entry(hass, roi={"mode": "battery", "savings_entity": "sensor.battery_savings", "before": 50})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.recalculate()
    hass.states.async_set("sensor.battery_savings", "815.90", {"unit_of_measurement": "AUD"})
    entry.runtime_data.recalculate()
    await hass.async_block_till_done()
    s = hass.states.get("sensor.battery_ledger_savings_to_date")
    assert float(s.state) == pytest.approx(865.90)
    assert s.attributes["today"] == pytest.approx(3.5)
    assert hass.states.get("sensor.battery_ledger_return_on_investment").attributes["investment"] == 20000


async def test_repairs_asks_for_a_choice(hass: HomeAssistant):
    """A setup without an ROI choice (any from before 0.4.0) gets a Repairs notice; its fix is the ROI form, and
    any choice, Off included, ends it for good."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.battery_ledger.repairs import async_create_fix_flow

    entry = await _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"roi_not_set_up_{entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.is_fixable and issue.translation_placeholders == {"entry": "Home"}

    flow = await async_create_fix_flow(hass, issue_id, {"entry_id": entry.entry_id})
    flow.hass = hass
    r = await flow.async_step_init()
    assert r["step_id"] == "roi"
    r = await flow.async_step_roi({"mode": "installation"})  # no Home Energy Advisor here
    assert r["errors"] == {"base": "hea_not_available"}
    r = await flow.async_step_roi({"mode": "off"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data["roi"] == {"mode": "off"}
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    # Not raised again on the next start
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repairs_fix_sets_up_whole_installation(hass: HomeAssistant):
    from homeassistant.helpers import issue_registry as ir

    from custom_components.battery_ledger.repairs import async_create_fix_flow

    _fake_hea(hass)
    entry = await _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"roi_not_set_up_{entry.entry_id}"
    flow = await async_create_fix_flow(hass, issue_id, {"entry_id": entry.entry_id})
    flow.hass = hass
    r = await flow.async_step_roi({"mode": "installation", "before": 250})
    assert r["step_id"] == "roi_plan"
    r = await flow.async_step_roi_plan({"plan_id": "red"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data["roi"]["plan_id"] == "red" and entry.data["roi"]["before"] == 250
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    await _settle(hass, entry)
    assert hass.states.get("sensor.battery_ledger_savings_to_date") is not None
