"""Camera entity showing the detector's frames, changed pixels in red.

It serves the frames the detector already decodes, instead of giving Home
Assistant the RTSP address, so the camera only ever has one connection.
"""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RtspMotionConfigEntry
from .entity import VideoEntity
from .hub import RtspMotionHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RtspMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RtspMotionCamera(entry.runtime_data)])


class RtspMotionCamera(VideoEntity, Camera):
    _attr_name = None  # the device name
    _attr_frame_interval = 0.2  # live view refresh (MJPEG), seconds

    def __init__(self, hub: RtspMotionHub) -> None:
        VideoEntity.__init__(self, hub, "camera")
        Camera.__init__(self)
        self._attr_translation_key = None

    @property
    def is_on(self) -> bool:
        return self.hub.connected

    @property
    def motion_detection_enabled(self) -> bool:
        return not self.hub.detector.paused

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(self.hub.latest_jpeg)
