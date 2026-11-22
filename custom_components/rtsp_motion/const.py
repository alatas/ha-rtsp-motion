"""Constants for RTSP Motion."""
from __future__ import annotations

DOMAIN = "rtsp_motion"

CONF_PATH = "path"

CONF_MIN_PERCENT = "min_percent"
CONF_PIXEL_THRESHOLD = "pixel_threshold"
CONF_CONFIRM_FRAMES = "confirm_frames"
CONF_HOLD_SECONDS = "hold_seconds"
CONF_IGNORE_AREAS = "ignore_areas"
CONF_COMPARE_SECONDS = "compare_seconds"

DEFAULT_PORT = 554
DEFAULT_PATH = "live0"
DEFAULT_MIN_PERCENT = 0.5
DEFAULT_PIXEL_THRESHOLD = 25
DEFAULT_CONFIRM_FRAMES = 3
DEFAULT_HOLD_SECONDS = 5.0
DEFAULT_COMPARE_SECONDS = 0.5
# x,y,width,height in percent of the picture; ';' between areas. Default: camera clock.
DEFAULT_IGNORE_AREAS = "65,0,35,12"

EVENT = f"{DOMAIN}_event"

# Event / device trigger types
MOTION_DETECTED = "motion_detected"
MOTION_UPDATED = "motion_updated"  # internal: the peak change grew during a motion
MOTION_CLEARED = "motion_cleared"
VIDEO_LOST = "video_lost"
VIDEO_CONNECTED = "video_connected"
TRIGGER_TYPES = [MOTION_DETECTED, MOTION_CLEARED, VIDEO_LOST, VIDEO_CONNECTED]

ATTR_PERCENT = "percent"
CONF_ABOVE = "above"
