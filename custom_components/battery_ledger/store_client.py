"""Fetch, cache and search the BatteryLedger Store index.

Lookups need no GitHub account: the index is a public JSON file on GitHub Pages.
It is cached in Home Assistant's .storage, and a snapshot bundled with each release
is used until the first successful download (or if GitHub can't be reached).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import ANY, DOMAIN, STORE_INDEX_URL, STORE_REFRESH_INTERVAL, SUPPORTED_INDEX_FORMAT

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(__file__).parent / "data" / "index_snapshot.json"
STORAGE_KEY = f"{DOMAIN}.store_index"
STORAGE_VERSION = 1

SOURCE_DOWNLOADED = "downloaded"
SOURCE_BUNDLED = "bundled"


class StoreIndexError(Exception):
    """The Store index couldn't be fetched or understood."""


def _check_index(data: Any) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("specs"), list):
        raise StoreIndexError("index is not in the expected format")
    if data.get("index_format") != SUPPORTED_INDEX_FORMAT:
        raise StoreIndexError(
            f"index format {data.get('index_format')} isn't supported by this version; update BatteryLedger")
    specs = [
        s for s in data["specs"]
        if isinstance(s, dict) and {"id", "brand", "model", "regions", "phases", "capacity", "warranty"} <= s.keys()
    ]
    return {**data, "specs": specs}


class StoreIndex:
    """The Store index shared by all BatteryLedger entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict = {"specs": []}
        self.source: str = SOURCE_BUNDLED
        self.fetched_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._loaded = False

    async def async_load(self) -> None:
        if self._loaded:
            return
        cached = await self._store.async_load()
        if cached and cached.get("index"):
            try:
                self._data = _check_index(cached["index"])
                self.source = SOURCE_DOWNLOADED
                self.fetched_at = dt_util.parse_datetime(cached.get("fetched_at", ""))
                self._loaded = True
                return
            except StoreIndexError as err:
                _LOGGER.debug("Ignoring cached Store index: %s", err)
        raw = await self.hass.async_add_executor_job(SNAPSHOT_PATH.read_text, "utf-8")
        self._data = _check_index(json.loads(raw))
        self.source = SOURCE_BUNDLED
        self._loaded = True

    @property
    def is_stale(self) -> bool:
        return self.fetched_at is None or dt_util.utcnow() - self.fetched_at > STORE_REFRESH_INTERVAL

    async def async_refresh(self) -> int:
        """Download the latest index. Returns the number of specs. Raises StoreIndexError."""
        async with self._lock:
            session = async_get_clientsession(self.hass)
            try:
                async with asyncio.timeout(20):
                    resp = await session.get(STORE_INDEX_URL, headers={"Cache-Control": "no-cache"})
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise StoreIndexError(f"couldn't download the Store index: {err}") from err
            self._data = _check_index(data)
            self.source = SOURCE_DOWNLOADED
            self.fetched_at = dt_util.utcnow()
            self._loaded = True
            await self._store.async_save({"fetched_at": self.fetched_at.isoformat(), "index": self._data})
            return len(self._data["specs"])

    async def async_refresh_if_stale(self) -> None:
        if self.is_stale:
            try:
                await self.async_refresh()
            except StoreIndexError as err:
                _LOGGER.info("BatteryLedger Store refresh skipped: %s", err)

    # --- queries -------------------------------------------------------------

    @property
    def specs(self) -> list[dict]:
        return self._data["specs"]

    @property
    def generated(self) -> str | None:
        return self._data.get("generated")

    @property
    def profiles(self) -> list[dict]:
        return self._data.get("profiles", [])

    def profiles_for_brands(self, brands: set[str]) -> list[dict]:
        return [p for p in self.profiles if brands & set(p.get("brands", []))]

    def get(self, spec_id: str) -> dict | None:
        return next((s for s in self.specs if s["id"] == spec_id), None)

    def brands(self) -> list[str]:
        return sorted({s["brand"] for s in self.specs}, key=str.lower)

    def series(self) -> list[tuple[str, str]]:
        """(brand, series) pairs, e.g. ("Sigenergy", "SigenStor")."""
        return sorted({(s["brand"], s["series"]) for s in self.specs if s.get("series")},
                      key=lambda x: (x[0].lower(), x[1].lower()))

    def regions(self) -> list[str]:
        return sorted({r for s in self.specs for r in s["regions"]})

    def search(self, text: str = "", brand: str = ANY, region: str = ANY, phase: str = ANY,
               series: str = ANY) -> list[dict]:
        """series is ANY or "<brand>|<series>"."""
        words = text.lower().split()
        out = []
        for s in self.specs:
            if brand != ANY and s["brand"] != brand:
                continue
            if series != ANY and f"{s['brand']}|{s.get('series', '')}" != series:
                continue
            if region != ANY and region not in s["regions"] and "GLOBAL" not in s["regions"]:
                continue
            if phase != ANY and phase not in s["phases"]:
                continue
            hay = f"{s['brand']} {s.get('series', '')} {s['model']} {s.get('variant', '')} {s['id']}".lower()
            if all(w in hay for w in words):
                out.append(s)
        return out


def spec_label(spec: dict) -> str:
    """Dropdown label, data only: 'Sigenergy · SigenStor BAT 10.0 · AU/NZ · 1φ/3φ ✓' (✓ = verified)."""
    name = " ".join(x for x in (spec["model"], spec.get("variant")) if x)
    phases = "/".join(f"{p}φ" for p in spec["phases"])
    return f"{spec['brand']} · {name} · {'/'.join(spec['regions'])} · {phases}{' ✓' if spec.get('verified') else ''}"


async def async_get_store_index(hass: HomeAssistant) -> StoreIndex:
    """Shared StoreIndex instance, loaded on first use."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    index = domain_data.get("store_index")
    if index is None:
        index = domain_data["store_index"] = StoreIndex(hass)
    await index.async_load()
    return index
