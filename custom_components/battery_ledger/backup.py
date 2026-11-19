"""Download a setup as a JSON file (Configure → Export setup, or the card's Backup tab).

The file is served by an authenticated view; the link handed out is signed for a few minutes, so a plain
browser link (in a flow description or opened by the card) can download it. Admins only.
"""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus

from aiohttp import web
from homeassistant.components.http import KEY_HASS_USER, HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import DOMAIN
from .transfer import build_export, export_filename, export_text

EXPORT_PATH = f"/api/{DOMAIN}/export/{{entry_id}}"
LINK_LIFETIME = timedelta(minutes=5)


def async_export_link(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """A signed link to download this setup's file (valid for LINK_LIFETIME)."""
    return async_sign_path(hass, EXPORT_PATH.format(entry_id=entry.entry_id), LINK_LIFETIME)


async def async_export_file(hass: HomeAssistant, entry: ConfigEntry) -> tuple[str, str]:
    """(file name, JSON text) for a setup, with its card settings."""
    from .card import async_card_settings  # card imports this module

    today = dt_util.now().date()
    export = build_export(entry.title, dict(entry.data), dict(entry.options), today,
                          await async_card_settings(hass, entry.entry_id))
    return export_filename(slugify(entry.title), today), export_text(export)


class ExportView(HomeAssistantView):
    url = EXPORT_PATH
    name = f"api:{DOMAIN}:export"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        user = request[KEY_HASS_USER]
        if not user.is_admin:
            return web.Response(status=HTTPStatus.UNAUTHORIZED)
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        filename, text = await async_export_file(hass, entry)
        return web.Response(text=text, content_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="{filename}"'})
