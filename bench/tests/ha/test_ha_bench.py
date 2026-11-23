"""Home Assistant layer against the fake camera. Real time; run with -m bench_ha."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rtsp_motion.const import CONF_PATH, DOMAIN, EVENT

pytestmark = pytest.mark.bench_ha

SCENARIO_SECONDS = 60


def entry_data(name="night_walker", password="benchpass", path=None):
    return {
        CONF_HOST: "rtsp",
        CONF_PORT: 8554,
        CONF_PATH: path or f"synthetic-once/{name}",
        CONF_USERNAME: "bench",
        CONF_PASSWORD: password,
    }


async def _flow(hass, **kw):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Bench", **entry_data(**kw)})


@pytest.mark.timeout(60)
async def test_flow_wrong_password(hass):
    result = await _flow(hass, password="nope")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.timeout(60)
async def test_flow_missing_path(hass):
    result = await _flow(hass, path="nothing/here")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "stream_not_found"}


class Recorder:
    """Collects bus events with times relative to the first video_connected."""

    def __init__(self, hass):
        self.origin = None
        self.events = []  # (seconds since origin, type, percent)
        self.connected = asyncio.Event()
        hass.bus.async_listen(EVENT, self._on_event)

    @callback
    def _on_event(self, event):
        now = time.monotonic()
        kind = event.data["type"]
        if kind == "video_connected" and self.origin is None:
            self.origin = now
            self.connected.set()
        rel = None if self.origin is None else now - self.origin
        self.events.append((rel, kind, event.data.get("percent")))

    def types(self):
        return [e[1] for e in self.events]


async def _start(hass, name):
    rec = Recorder(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Bench", data=entry_data(name), unique_id=name)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, rec


async def _stop(hass, entry):
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.timeout(SCENARIO_SECONDS + 30)
async def test_walker_fires_device_trigger(hass):
    fired = []

    async def handler(call):
        fired.append(time.monotonic())

    hass.services.async_register("test", "automation", handler)
    entry, rec = await _start(hass, "night_walker")
    try:
        device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id)
        assert device is not None
        assert await async_setup_component(hass, "automation", {"automation": [{
            "alias": "walker",
            "triggers": [{"platform": "device", "domain": DOMAIN, "device_id": device.id,
                          "type": "motion_detected", "above": 1}],
            "actions": [{"action": "test.automation"}],
        }]})
        await hass.async_block_till_done()

        await asyncio.wait_for(rec.connected.wait(), 20)
        await asyncio.sleep(SCENARIO_SECONDS - 10)  # walker is gone at t=40; wait past it
        await hass.async_block_till_done()
    finally:
        await _stop(hass, entry)

    rel = [t - rec.origin for t in fired]
    print("device trigger fire times after origin:", rel, "events:", rec.events)
    assert len(fired) == 1, rec.events
    # The walker appears at scenario t=20. The origin (first video_connected) lags the
    # scenario clock by ~2 s (on-demand publisher start + first keyframe), so a ~1 s
    # pipeline lag lands at ~18 s after origin: window is [16.5, 22.5], measured ~17.9.
    assert 16.5 <= rel[0] <= 22.5, rel


@pytest.mark.timeout(SCENARIO_SECONDS + 30)
@pytest.mark.xfail(strict=True, reason=(
    "integration finding: av.open blocks until video resumes, so the LOST_GRACE check "
    "never runs during a frozen-but-open session (no video_lost event)"))
async def test_freeze_long_events(hass):
    entry, rec = await _start(hass, "freeze_long")
    try:
        await asyncio.wait_for(rec.connected.wait(), 20)
        await asyncio.sleep(SCENARIO_SECONDS - 10)
    finally:
        await _stop(hass, entry)
    print("freeze_long events:", rec.events)
    types = rec.types()
    assert types.count("video_lost") == 1, rec.events
    assert "video_connected" in types[types.index("video_lost"):], rec.events


@pytest.mark.timeout(60)
async def test_unload_stops_thread(hass):
    entry, rec = await _start(hass, "night_walker")
    await asyncio.wait_for(rec.connected.wait(), 20)
    assert any(t.name == "rtsp_motion" and t.is_alive() for t in threading.enumerate())
    await hass.config_entries.async_unload(entry.entry_id)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not any(t.name == "rtsp_motion" and t.is_alive() for t in threading.enumerate()):
            break
        await asyncio.sleep(0.1)
    assert not any(t.name == "rtsp_motion" and t.is_alive() for t in threading.enumerate())
