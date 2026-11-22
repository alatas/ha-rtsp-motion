"""Motion change (%) and frame rate sensors.

The change sensor holds the peak change of the current or last motion. It only
changes when motion is detected, so it doesn't flood the recorder.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RtspMotionConfigEntry
from .entity import RtspMotionEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RtspMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities([ChangeSensor(hub, "motion_change"), FpsSensor(hub, "frame_rate")])


class ChangeSensor(RtspMotionEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:image-filter-center-focus"

    @property
    def native_value(self) -> float | None:
        return self.hub.motion_percent


class FpsSensor(RtspMotionEntity, SensorEntity):
    _attr_native_unit_of_measurement = "fps"
    _attr_suggested_display_precision = 1
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:filmstrip"

    @property
    def native_value(self) -> float:
        return round(self.hub.fps, 1)
