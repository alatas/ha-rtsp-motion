"""RTSP Motion: pixel-change motion detection for any RTSP camera."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .hub import RtspMotionHub

PLATFORMS = [
    Platform.CAMERA,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.IMAGE,
    Platform.SWITCH,
]

type RtspMotionConfigEntry = ConfigEntry[RtspMotionHub]


async def async_setup_entry(hass: HomeAssistant, entry: RtspMotionConfigEntry) -> bool:
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="RTSP Motion",
        model="Pixel-change motion detector",
    )
    hub = RtspMotionHub(hass, entry, device.id)
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RtspMotionConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hub = entry.runtime_data
        hub.stop()
        # The reader notices the stop within its read timeout (4 s).
        await hass.async_add_executor_job(hub.detector.join, 6)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: RtspMotionConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
