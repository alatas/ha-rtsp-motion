"""Snapshot of the last motion, changed pixels in red."""
from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RtspMotionConfigEntry
from .entity import RtspMotionEntity
from .hub import RtspMotionHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RtspMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LastMotionImage(hass, entry.runtime_data)])


class LastMotionImage(RtspMotionEntity, ImageEntity):
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, hub: RtspMotionHub) -> None:
        RtspMotionEntity.__init__(self, hub, "last_motion")
        ImageEntity.__init__(self, hass)
        self._shown_motion = None

    @callback
    def _handle_hub_update(self) -> None:
        if self.hub.last_motion is not None and self.hub.last_motion != self._shown_motion:
            self._shown_motion = self.hub.last_motion
            self._attr_image_last_updated = self.hub.last_motion
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        return await self.hass.async_add_executor_job(self.hub.alarm_jpeg)
