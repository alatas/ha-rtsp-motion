from homeassistant.components.camera import async_get_image
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.setup import async_setup_component

from custom_components.rtsp_motion.const import DOMAIN, EVENT
from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service


def hub_of(entry):
    return entry.runtime_data


async def test_entities_follow_detector(hass, setup_entry, fake_detector):
    hub = hub_of(setup_entry)
    assert fake_detector.instances[0].started
    assert hass.states.get("binary_sensor.baby_room_motion").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.baby_room_video").state == STATE_OFF

    events = async_capture_events(hass, EVENT)
    hub.on_connected()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.baby_room_video").state == STATE_ON
    assert hass.states.get("binary_sensor.baby_room_motion").state == STATE_OFF
    assert hass.states.get("camera.baby_room").state != STATE_UNAVAILABLE

    hub.on_motion_start(1.234)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.baby_room_motion").state == STATE_ON
    assert hass.states.get("sensor.baby_room_motion_change").state == "1.23"
    image_state = hass.states.get("image.baby_room_last_motion")
    assert image_state.state not in ("unknown", STATE_UNAVAILABLE)

    hub.on_motion_update(7.5)
    hub.on_motion_end(7.5)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.baby_room_motion").state == STATE_OFF
    assert hass.states.get("sensor.baby_room_motion_change").state == "7.5"

    hub.on_disconnected("test")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.baby_room_video").state == STATE_OFF
    assert hass.states.get("binary_sensor.baby_room_motion").state == STATE_UNAVAILABLE

    assert [e.data["type"] for e in events] == [
        "video_connected", "motion_detected", "motion_updated", "motion_cleared", "video_lost"
    ]
    assert events[1].data["percent"] == 1.23


async def test_camera_image_is_jpeg(hass, setup_entry):
    hub_of(setup_entry).on_connected()
    await hass.async_block_till_done()
    image = await async_get_image(hass, "camera.baby_room")
    assert image.content_type == "image/jpeg"
    assert image.content[:2] == b"\xff\xd8"


async def test_switch_pauses_detection(hass, setup_entry, fake_detector):
    detector = fake_detector.instances[0]
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.baby_room_motion_detection"}, blocking=True
    )
    assert detector.paused
    assert hass.states.get("switch.baby_room_motion_detection").state == STATE_OFF
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.baby_room_motion_detection"}, blocking=True
    )
    assert not detector.paused


async def test_unload_stops_detector(hass, setup_entry, fake_detector):
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    assert fake_detector.instances[0].stopped


async def test_device_triggers(hass, setup_entry):
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get(hub_of(setup_entry).device_id)
    assert (DOMAIN, setup_entry.entry_id) in device.identifiers
    calls = async_mock_service(hass, "test", "automation")

    def automation(alias, trigger_type, **extra):
        return {
            "alias": alias,
            "triggers": [{"platform": "device", "domain": DOMAIN, "device_id": device.id,
                          "type": trigger_type, **extra}],
            "actions": [{"action": "test.automation",
                         "data": {"alias": alias, "percent": "{{ trigger.percent }}"}}],
        }

    assert await async_setup_component(hass, "automation", {"automation": [
        automation("any", "motion_detected"),
        automation("big", "motion_detected", above=5),
        automation("lost", "video_lost"),
    ]})
    await hass.async_block_till_done()

    from homeassistant.components.device_automation import async_get_device_automations, DeviceAutomationType
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, [device.id])
    assert {t["type"] for t in triggers[device.id]} >= {
        "motion_detected", "motion_cleared", "video_lost", "video_connected"
    }

    hub = hub_of(setup_entry)
    hub.on_connected()
    hub.on_motion_start(1.0)        # "any" fires; "big" waits
    hub.on_motion_update(6.0)       # "big" fires once
    hub.on_motion_update(8.0)       # nothing more this motion
    hub.on_motion_end(8.0)
    hub.on_motion_start(9.0)        # new motion: both fire
    hub.on_disconnected("x")        # "lost" fires
    await hass.async_block_till_done()

    def pct(value):
        return None if value in (None, "", "None") else float(value)

    fired = [(c.data["alias"], pct(c.data["percent"])) for c in calls]
    assert fired == [("any", 1.0), ("big", 6.0), ("any", 9.0), ("big", 9.0), ("lost", None)]
