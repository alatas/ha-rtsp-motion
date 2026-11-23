"""Home Assistant layer against the fake camera. Real time; run with -m bench_ha."""
from __future__ import annotations

import asyncio
import threading
import time
import uuid

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
        CONF_PATH: path or f"synthetic-once/{name}/{uuid.uuid4().hex[:12]}",
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
    # mediamtx answers 400 for unconfigured paths and the integration maps only 404 to
    # stream_not_found (an integration finding), so mediamtx.yml configures `nothing/.+`
    # as a never-published path, which answers 404 like a real camera.
    result = await _flow(hass, path="nothing/here")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "stream_not_found"}


class Recorder:
    """Collects bus events. Event times are relative to the first video_connected (origin);
    t0 is the setup start, so `time - t0` gives times relative to setup start."""

    def __init__(self, hass):
        self.origin = None
        self.t0 = time.monotonic()  # setup start
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

    rel = [t - rec.t0 for t in fired]
    print("device trigger fire times after setup start:", rel,
          "origin at", rec.origin - rec.t0, "events:", rec.events)
    assert len(fired) == 1, rec.events
    assert 19.0 <= rel[0] <= 22.5, rel


@pytest.mark.timeout(SCENARIO_SECONDS + 30)
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "integration finding: av.open blocks until video resumes, so the LOST_GRACE check "
    "never runs during a frozen-but-open session (no video_lost event)"))
async def test_freeze_long_events(hass):
    entry, rec = await _start(hass, "freeze_long")
    try:
        # Setup problems must fail loudly (not AssertionError), not count as the finding.
        await asyncio.wait_for(rec.connected.wait(), 20)
        await asyncio.sleep(SCENARIO_SECONDS - 10)
    finally:
        # No assert here: it would be swallowed as the xfail's AssertionError.
        unloaded = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    if not unloaded:
        raise RuntimeError("config entry did not unload")  # not the known finding
    print("freeze_long events:", rec.events)
    types = rec.types()
    assert "video_connected" in types, rec.events
    # Expected failure below: the known finding.
    assert types.count("video_lost") == 1, rec.events
    assert "video_connected" in types[types.index("video_lost"):], rec.events


def _thread_alive():
    return any(t.name == "rtsp_motion" and t.is_alive() for t in threading.enumerate())


@pytest.mark.timeout(60)
async def test_unload_stops_thread(hass):
    entry, rec = await _start(hass, "night_walker")
    unloaded = False
    try:
        await asyncio.wait_for(rec.connected.wait(), 20)
        assert _thread_alive()
        unloaded = await hass.config_entries.async_unload(entry.entry_id)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _thread_alive():
            await asyncio.sleep(0.1)
        assert unloaded
        assert not _thread_alive()
    finally:
        if not unloaded:
            assert await hass.config_entries.async_unload(entry.entry_id)
