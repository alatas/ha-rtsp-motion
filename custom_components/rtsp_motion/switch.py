"""Switch to pause motion detection (video keeps running)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RtspMotionConfigEntry
from .entity import RtspMotionEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RtspMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([DetectionSwitch(entry.runtime_data, "motion_detection")])


class DetectionSwitch(RtspMotionEntity, SwitchEntity, RestoreEntity):
    _attr_icon = "mdi:motion-sensor"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.hub.detector.paused = last.state == STATE_OFF

    @property
    def is_on(self) -> bool:
        return not self.hub.detector.paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.detector.paused = False
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.detector.paused = True
        self.async_write_ha_state()
