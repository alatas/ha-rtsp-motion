"""Shared fixtures: a fake detector so tests never touch a real camera."""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rtsp_motion.const import CONF_PATH, DOMAIN

ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 554,
    CONF_PATH: "live0",
    CONF_USERNAME: "user",
    CONF_PASSWORD: "p@ss:word",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeDetector:
    instances: list["FakeDetector"] = []

    def __init__(self, url, settings, callbacks):
        self.url = url
        self.settings = settings
        self.callbacks = callbacks
        self.paused = False
        self.started = False
        self.stopped = False
        self.image = np.zeros((36, 64, 3), dtype=np.uint8)
        FakeDetector.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        pass

    def latest_image(self, mark_changes=True):
        return self.image

    def alarm_image(self):
        return self.image


@pytest.fixture
def fake_detector():
    FakeDetector.instances.clear()
    with patch("custom_components.rtsp_motion.hub.MotionDetector", FakeDetector):
        yield FakeDetector


@pytest.fixture
async def setup_entry(hass, fake_detector):
    entry = MockConfigEntry(domain=DOMAIN, title="Baby room", data=ENTRY_DATA, unique_id="x")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
