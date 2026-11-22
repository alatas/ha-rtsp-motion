from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.rtsp_motion.config_flow import CannotConnect
from custom_components.rtsp_motion.const import CONF_IGNORE_AREAS, CONF_MIN_PERCENT, DOMAIN
from custom_components.rtsp_motion.hub import build_url

from .conftest import ENTRY_DATA

PROBE = "custom_components.rtsp_motion.config_flow.probe_stream"


async def test_user_flow_success(hass, fake_detector):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(PROBE, return_value=(1920, 1080)) as probe:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Baby room", **ENTRY_DATA}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Baby room"
    assert result["data"] == ENTRY_DATA
    # Username/password are URL-encoded (':' and '@' in the password).
    assert probe.call_args[0][0] == "rtsp://user:p%40ss%3Aword@192.0.2.10:554/live0"


async def test_user_flow_errors_then_duplicate(hass, fake_detector):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    for error in ("invalid_auth", "stream_not_found", "cannot_connect"):
        with patch(PROBE, side_effect=CannotConnect(error)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_NAME: "Cam", **ENTRY_DATA}
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}

    with patch(PROBE, return_value=(1920, 1080)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Cam", **ENTRY_DATA}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(PROBE, return_value=(1920, 1080)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Again", **ENTRY_DATA}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_reloads_with_new_settings(hass, setup_entry, fake_detector):
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    bad = {CONF_MIN_PERCENT: 2, "pixel_threshold": 30, "confirm_frames": 2,
           "hold_seconds": 10, CONF_IGNORE_AREAS: "65,0,35"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {CONF_IGNORE_AREAS: "invalid_areas"}

    good = {**bad, CONF_IGNORE_AREAS: "65,0,35,12; 0,80,20,20"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], good)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    detector = fake_detector.instances[-1]  # the reload created a new one
    assert detector.settings.min_percent == 2
    assert detector.settings.masks == [(0.65, 0.0, 0.35, 0.12), (0.0, 0.8, 0.2, 0.2)]
    assert fake_detector.instances[0].stopped


async def test_options_flow_empty_areas_watches_everything(hass, setup_entry, fake_detector):
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_MIN_PERCENT: 0.5, "pixel_threshold": 25, "confirm_frames": 3, "hold_seconds": 5},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert fake_detector.instances[-1].settings.masks == []


def test_build_url_without_credentials():
    assert build_url({"host": "cam", "port": 8554, "path": "/a/b"}) == "rtsp://cam:8554/a/b"
