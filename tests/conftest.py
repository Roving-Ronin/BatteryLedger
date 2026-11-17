from unittest.mock import patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def offline_store():
    """No network in tests: Store refreshes fail, so the bundled snapshot is used."""
    from custom_components.battery_ledger.store_client import StoreIndexError

    with patch("custom_components.battery_ledger.store_client.StoreIndex.async_refresh",
               side_effect=StoreIndexError("offline")):
        yield
