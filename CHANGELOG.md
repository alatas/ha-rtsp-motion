# Changelog

All notable changes to RTSP Motion. Versions follow the `version` in
`custom_components/rtsp_motion/manifest.json`.

## 0.1.5 (not released yet)

### New

- **See the ignored areas on the picture.** The Configure form shows the camera's
  current picture with the ignored areas (exclusion zones) shaded and a 10% grid, so
  you can read the numbers off it. When you change them, you see the new areas on the
  picture before saving. The Last motion picture shades them too.

### Fixes

- **Reconfigure can change the address.** A camera that got a new IP address can now
  be updated with ⋮ → Reconfigure instead of being removed and added again. The device
  stays the same, so automations that use its triggers keep working. An address
  another camera already uses is refused.
- **Video interrupted now fires for a frozen camera.** A camera that stops sending
  video but keeps the connection open was never reported. The 15 s grace now counts
  from the last picture received.
- **Motion ends when the video stops.** Motion no longer stays on until the stream
  reconnects.
- **Camera clock jumps** no longer end and restart a motion.
- **No false motion right after connecting** from a broken or half-decoded first
  picture: detection starts shortly after the video does, and the picture filling in
  at the next keyframe no longer counts as motion.
- **Faster detection,** especially at low frame rates. Pictures are no longer held
  back while decoding (up to several seconds at 2 fps).
- **Motion change drops to 0 when motion clears.** It used to keep the last peak until
  the next motion, which showed as a flat line on the timeline. The peak of each
  motion is still in the history and in the `motion_cleared` event. If an automation
  checks *Motion change above X*, it now only matches while motion is on.
- **Motion hold time** now counts from the moment the change was seen, not from when
  it was confirmed, so motion clears on time at low frame rates.

### Documentation

- README: logo, screenshots, and a section on setting ignored areas.

## 0.1.4 (2026-11-23)

### Fixes

- Camera usernames and passwords are no longer written to the Home Assistant log
  (FFmpeg error messages included the full RTSP address). Update recommended.
- Short stream drops (a few seconds) now reconnect quietly. **Video** turns off and
  **Video interrupted** fires only after 15 seconds without video, instead of on
  every brief stall.
- A running motion ends when the stream reconnects, so **Motion** can't get stuck on.

## 0.1.3 (2026-11-23)

### Fixes

- Default pixel sensitivity is 15 (was 25), so movement in low-contrast night vision
  pictures is detected.

## 0.1.2 (2026-11-23)

### Fixes

- Each frame is compared with the frame from 0.5 s earlier (instead of the previous
  frame), so slow and distant movement shows up as a whole shape and is detected.

## 0.1.1 (2026-11-23)

### Fixes

- A grayscale conversion overflow hid normal motion.
- **Last motion** is unavailable until the first snapshot, instead of showing an
  empty picture.

## 0.1.0 (2026-11-23)

First version.

- Pixel-change motion detection for any RTSP camera, set up from the UI.
- Entities: camera (live picture, changes in red), Motion, Motion change, Last motion
  picture, a switch to pause detection, and Video and Frame rate diagnostics.
- Device triggers: motion detected or cleared, video interrupted or connected.
