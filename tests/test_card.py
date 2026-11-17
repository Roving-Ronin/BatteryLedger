"""The dashboard card's websocket commands: setups for the card, and its saved settings."""

from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.battery_ledger.card import CARD_FILE, DEFAULT_SETTINGS

from test_integration import _setup_via_flow


async def test_card_setups_and_settings(hass: HomeAssistant, hass_ws_client):
    entry = await _setup_via_flow(hass, "2025-01-01")
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "battery_ledger/card/setups"})
    res = await client.receive_json()
    assert res["success"]
    [setup] = res["result"]["setups"]
    assert setup["entry_id"] == entry.entry_id
    assert setup["title"] == "Sigen battery"
    # Found by unique ID, so a renamed entity is still found
    assert setup["entities"]["total_rated_throughput"] == "sensor.battery_ledger_total_rated_throughput"
    assert setup["entities"]["cost_consumed_to_date"] == "sensor.battery_ledger_cost_consumed_to_date"
    [group] = setup["groups"]
    assert group["model"] == "SigenStor BAT 8.0" and group["units"] == 6
    assert group["install_date"] == "2025-01-01" and group["warranty_years"] == 10
    assert setup["currency"] == "AUD"
    assert setup["settings"] == DEFAULT_SETTINGS

    settings = {"cost_decimals": 2, "sections": {"warranty": True, "throughput": False, "cost": True, "health": True}}
    await client.send_json_auto_id({"type": "battery_ledger/card/save_settings",
                                    "entry_id": entry.entry_id, "settings": settings})
    res = await client.receive_json()
    assert res["success"] and res["result"]["settings"] == settings

    await client.send_json_auto_id({"type": "battery_ledger/card/setups"})
    assert (await client.receive_json())["result"]["setups"][0]["settings"] == settings

    # Out-of-range decimals and unknown setups are refused
    await client.send_json_auto_id({"type": "battery_ledger/card/save_settings", "entry_id": entry.entry_id,
                                    "settings": {**settings, "cost_decimals": 9}})
    assert not (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "battery_ledger/card/save_settings", "entry_id": "nope",
                                    "settings": settings})
    res = await client.receive_json()
    assert not res["success"] and res["error"]["code"] == "not_found"

    # Removing the setup forgets its card settings
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    from custom_components.battery_ledger.card import _settings_store
    _, saved = await _settings_store(hass)
    assert entry.entry_id not in saved


async def test_card_settings_need_admin(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    entry = await _setup_via_flow(hass, "2025-01-01")
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "battery_ledger/card/setups"})
    assert (await client.receive_json())["success"]  # anyone can view the card
    await client.send_json_auto_id({"type": "battery_ledger/card/save_settings", "entry_id": entry.entry_id,
                                    "settings": DEFAULT_SETTINGS})
    res = await client.receive_json()
    assert not res["success"] and res["error"]["code"] == "unauthorized"


def test_card_file_ships():
    assert Path(CARD_FILE).is_file()
    text = Path(CARD_FILE).read_text(encoding="utf-8")
    assert 'customElements.define("battery-ledger-card"' in text
    assert "battery_ledger/card/setups" in text and "battery_ledger/card/save_settings" in text
