# RTSP Motion for Home Assistant

Simple pixel-change motion detection for any RTSP camera. It compares each video
frame with the one from half a second earlier and reports motion when more than a
set percentage of the picture changes. No AI, no cloud, no extra add-on.

It detects *change*: someone moving is detected, someone standing still is not.

## What you get

Add a camera under **Settings → Devices & services → Add integration → RTSP Motion**
with its host, port, stream path, username and password. The stream is tested
before it's saved.

Each camera becomes a device with:

| Entity | What it shows |
|---|---|
| Camera | Live picture with the changed pixels in red |
| Motion | On while a change is detected |
| Motion change | Peak change (%) of the current or last motion |
| Last motion | Snapshot of the last motion, changed pixels in red |
| Motion detection | Switch to pause detection (video keeps running) |
| Video | Diagnostic: is the camera sending video |
| Frame rate | Diagnostic: frames per second received |

The camera entity shows the frames this integration already reads, so the camera
only gets **one** connection.

### Automation triggers

In the automation editor, pick the device and one of:

- **Motion detected**, with an optional *Only when the change reaches (%)*.
  It fires once per motion, as soon as the change reaches that value.
- **Motion cleared**
- **Video interrupted**
- **Video connected**

The change is available in templates as `{{ trigger.percent }}`.

Example: turn on a light when more than 5% of the picture changes:

```yaml
triggers:
  - trigger: device
    domain: rtsp_motion
    device_id: <your camera device>
    type: motion_detected
    above: 5
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
```

## Settings

**Configure** on the integration opens:

| Setting | Default | Meaning |
|---|---|---|
| Minimum change | 0.5 % | Percent of the picture that must change. Higher = less sensitive. |
| Pixel sensitivity | 15 | How much a pixel's brightness (0–255) must change to count. Raise it if camera noise triggers motion. |
| Compare with frame from | 0.5 s | Each frame is compared with the frame from this long ago. Longer catches slow or distant movement (someone walking in from far away); 0 = the previous frame. |
| Confirm frames | 3 | Frames to wait to confirm a change is still there. Filters out one-frame video glitches. 0 = off. |
| Motion hold time | 5 s | Motion stays on this long after the last change. |
| Ignored areas | `65,0,35,12` | `x,y,width,height` in percent, separated by `;`. The default is the top-right corner, where many cameras show a clock. Empty = whole picture. |

To change the address or password, use **⋮ → Reconfigure** on the integration.

## Installation

### Marketplace (Home Assistant 2026.11 and newer)

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=alatas&repository=ha-rtsp-motion&category=integration)

Click the button, or in **Settings → Marketplace** add
`https://github.com/alatas/ha-rtsp-motion` as a custom *Integration* repository.
Download **RTSP Motion**, then restart Home Assistant.

### HACS (Home Assistant 2026.10 and older)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alatas&repository=ha-rtsp-motion&category=integration)

Click the button, or in HACS → ⋮ → **Custom repositories** add
`https://github.com/alatas/ha-rtsp-motion` as an *Integration*. Download
**RTSP Motion**, then restart Home Assistant.

### Manual

Copy `custom_components/rtsp_motion` into your Home Assistant `config/custom_components/`
folder and restart Home Assistant.

## Notes

- Detection runs on a 640-pixel-wide copy of each frame. Decoding the video is
  most of the CPU cost, so a high-resolution stream needs more CPU.
- If the stream freezes for 4 seconds, it reconnects by itself and the
  **Video interrupted** / **Video connected** triggers fire.
- Tested with Home Assistant 2026.5 and 2026.10. It uses PyAV and numpy, which
  Home Assistant already includes.

## Development

Tests use `pytest-homeassistant-custom-component` and need Linux (or WSL):

```bash
pip install -r requirements_test.txt
pytest
```

GitHub Actions run Home Assistant's `hassfest`, the HACS validator and the tests on
every push.

## License

MIT, see [LICENSE](LICENSE).
