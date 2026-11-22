"""Motion and video-connected binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RtspMotionConfigEntry
from .const import ATTR_PERCENT
from .entity import RtspMotionEntity, VideoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RtspMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities([MotionSensor(hub, "motion"), ConnectedSensor(hub, "video_connected")])


class MotionSensor(VideoEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.MOTION

    @property
    def is_on(self) -> bool:
        return self.hub.motion

    @property
    def extra_state_attributes(self) -> dict:
        return {ATTR_PERCENT: self.hub.motion_percent}


class ConnectedSensor(RtspMotionEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.hub.connected
