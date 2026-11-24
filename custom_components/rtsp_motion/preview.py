"""Picture of the ignored areas for the settings form.

The form shows it as a markdown image. A browser loads <img> without the login
header, so the URL carries a short-lived signature (async_sign_path) instead.
"""
from __future__ import annotations

import time
from datetime import timedelta
from http import HTTPStatus
from urllib.parse import urlencode

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .hub import RtspMotionHub, parse_areas

URL = "/api/rtsp_motion/{entry_id}/areas.jpg"
SIGN_FOR = timedelta(minutes=30)
_REGISTERED = f"{DOMAIN}_preview_view"


def async_register_view(hass: HomeAssistant) -> None:
    if not hass.data.get(_REGISTERED):
        hass.http.register_view(AreasPreviewView())
        hass.data[_REGISTERED] = True


def preview_markdown(hass: HomeAssistant, entry: ConfigEntry, areas_text: str) -> str:
    """Markdown image of the live picture with these areas, or a note when the camera
    has no picture yet. areas_text must already be valid."""
    hub: RtspMotionHub | None = getattr(entry, "runtime_data", None)
    if hub is None or hub.detector.latest_image(mark_changes=False) is None:
        return "*No camera picture yet, so no preview. The camera isn't connected.*"
    # Written compactly (no spaces), so the markdown link stays one token. t= makes
    # every opening a new URL, so the browser never shows a stale picture.
    areas = ";".join(",".join(f"{v * 100:g}" for v in a) for a in parse_areas(areas_text))
    query = urlencode({"areas": areas, "t": int(time.time())})
    path = async_sign_path(hass, f"{URL.format(entry_id=entry.entry_id)}?{query}", SIGN_FOR)
    return f"![Ignored areas on the camera picture]({path})"


class AreasPreviewView(HomeAssistantView):
    url = URL
    name = "api:rtsp_motion:areas"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        hass = request.app[KEY_HASS]
        entry = hass.config_entries.async_get_entry(entry_id)
        hub = getattr(entry, "runtime_data", None) if entry and entry.domain == DOMAIN else None
        if hub is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        try:
            areas = parse_areas(request.query.get("areas", ""))
        except ValueError:
            return web.Response(status=HTTPStatus.BAD_REQUEST)
        jpeg = await hass.async_add_executor_job(hub.areas_jpeg, areas)
        if jpeg is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.Response(body=jpeg, content_type="image/jpeg",
                            headers={"Cache-Control": "no-store"})
