"""Device triggers: motion detected (optionally above X %), motion cleared, video lost/connected.

"Motion detected above X %" fires once per motion, as soon as the motion's peak
change reaches X, even if the motion started smaller.
"""
from __future__ import annotations

try:  # Home Assistant 2026.6+ replaced voluptuous with probatio
    import probatio as vol
except ImportError:
    import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, Event, HassJob, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_PERCENT,
    CONF_ABOVE,
    DOMAIN,
    EVENT,
    MOTION_DETECTED,
    MOTION_UPDATED,
    TRIGGER_TYPES,
)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Optional(CONF_ABOVE): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    }
)


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, str]]:
    return [
        {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id, CONF_TYPE: t}
        for t in TRIGGER_TYPES
    ]


async def async_get_trigger_capabilities(hass: HomeAssistant, config: ConfigType) -> dict:
    if config[CONF_TYPE] != MOTION_DETECTED:
        return {}
    return {
        "extra_fields": vol.Schema(
            {vol.Optional(CONF_ABOVE): vol.All(vol.Coerce(float), vol.Range(min=0, max=100))}
        )
    }


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    device_id = config[CONF_DEVICE_ID]
    trigger_type = config[CONF_TYPE]
    above = config.get(CONF_ABOVE)
    trigger_data = trigger_info["trigger_data"]
    job = HassJob(action, f"{DOMAIN} device trigger {trigger_type}")
    fired_this_motion = False

    def _fire(event: Event) -> None:
        percent = event.data.get(ATTR_PERCENT)
        description = f"{DOMAIN} {trigger_type}"
        if percent is not None:
            description += f" ({percent:.2f}%)"
        hass.async_run_hass_job(
            job,
            {
                "trigger": {
                    **trigger_data,
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: trigger_type,
                    ATTR_PERCENT: percent,
                    "event": event,
                    "description": description,
                }
            },
            event.context,
        )

    @callback
    def _handle(event: Event) -> None:
        nonlocal fired_this_motion
        kind = event.data.get("type")
        if trigger_type != MOTION_DETECTED:
            if kind == trigger_type:
                _fire(event)
            return
        if kind == MOTION_DETECTED:
            fired_this_motion = False
        elif kind != MOTION_UPDATED or fired_this_motion:
            return
        if above is None:
            if kind == MOTION_DETECTED:
                fired_this_motion = True
                _fire(event)
        elif (event.data.get(ATTR_PERCENT) or 0) >= above:
            fired_this_motion = True
            _fire(event)

    @callback
    def _filter(event_data) -> bool:
        return event_data.get(CONF_DEVICE_ID) == device_id

    return hass.bus.async_listen(EVENT, _handle, event_filter=_filter)
