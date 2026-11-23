"""Fixtures for the Home Assistant bench layer (real time, real fake camera)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# /repo must be importable so `custom_components.rtsp_motion` resolves.
REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
