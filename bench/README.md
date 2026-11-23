# RTSP Motion fake-camera bench

A Docker test bench for the RTSP Motion integration. A fake camera (mediamtx plus a
publisher that renders synthetic scenes with known ground truth, or replays video
files) serves RTSP streams. The runner connects the real detector to them and scores
what it reports against the truth: did it see the motion, how late, and did it raise
false alarms or get stuck. A second layer runs the integration inside Home Assistant
against the same camera.

Everything runs in one image (`bench/Dockerfile`, Python 3.14 plus mediamtx, versions
pinned). The repo
is mounted into the containers, so code changes need no rebuild.

## Quick start

```bash
docker compose -f bench/docker-compose.yml up -d rtsp
docker compose -f bench/docker-compose.yml run --rm runner python -m runner synthetic --parallel 6
```

Results are written to `bench/results/`: `synthetic.md` and `synthetic.json`
(`virat.md` and `virat.json` for the VIRAT run). Set the environment variable
`BENCH_RESULTS_DIR` to write somewhere else.

- `--only NAME` runs one scenario (an unknown name lists the valid ones).
- `--parallel N` runs N scenarios at once (default 1; the full set takes about 2.5
  minutes at 6). Above 6 the on-demand publishers start late and timing skews: the
  runner warns, and rows whose connect offset is far from the median are flagged
  "(timing skew)".
- Home Assistant layer (real time, about 2 minutes):
  `docker compose -f bench/docker-compose.yml run --rm runner pytest tests/ha -m bench_ha`
- Unit tests:
  `docker compose -f bench/docker-compose.yml run --rm runner pytest tests -m "not bench_ha"`

On Windows with Git Bash, prefix the commands with `MSYS_NO_PATHCONV=1`. Otherwise
container paths such as `/data/virat` are rewritten into Windows paths.

CI runs the same steps in the `bench` job of `.github/workflows/validate.yml`
(`continue-on-error`, results uploaded as the `bench-synthetic` artifact).

## Scenarios

Streams are 1280x720 at 15 fps with sensor-like noise unless noted. A "walker" is a
bright box that crosses the picture. The clock area (top right) is the ignored area.

| Scenario | Duration | What it does | Truth | Expectation |
|---|---|---|---|---|
| `quiet_night` | 60 s | Noise only | none | no alarm |
| `night_walker` | 60 s | Walker from 20 s to 40 s | 20-40 s | one motion, no false alarm |
| `lights_on` | 40 s | Whole picture brightens at 20 s | 20-21 s | detected, and it ends (not stuck) |
| `slow_dusk` | 60 s | Brightness drifts down slowly, fresh noise every frame | none | no alarm |
| `clock_corner` | 60 s | A seven-segment clock changes every second inside the ignored area | none | no alarm |
| `glitch_burst` | 60 s | One white frame every 2 s (decode glitch) | none | no alarm |
| `freeze_short` | 60 s | Stream stops for 3 s at 20 s, session stays open | none | no alarm, no video lost |
| `freeze_long` | 60 s | Stream stops for 25 s at 20 s, session stays open | none | exactly 1 video lost |
| `size_change` | 60 s | Walkers at 10-20 s and 40-50 s; at 15 s the stream restarts at 1920x1080 | 10-20 s, 40-50 s | both detected |
| `pts_back` | 60 s | Walker 10-15 s; at 16 s the stream restarts with timestamps 3600 s earlier | 10-15 s | detected |
| `pts_forward` | 60 s | Walker 10-30 s; at 20 s timestamps jump 3600 s forward | 10-30 s | detected |
| `low_fps` | 60 s | 2 fps, walker 20-40 s moving 22 px per frame | 20-40 s | detected |

There is also `static` (a constant image, endless). The HA layer and smoke tests use
it; it is not part of the synthetic run.

Notes on what the bench can and cannot do:

- Streams that play once are read from `synthetic-once/<scenario>/<token>` and
  `virat-once/<clip>/<token>`. The runner appends a fresh token to every run, so each run
  gets its own publisher that starts at t=0 (mediamtx keeps a publisher for 5 s after
  its last reader leaves, and reconnects need that). Looping streams stay at
  `synthetic/<scenario>` and `virat/<clip>`.
- Ctrl-C stops a run, writes the report for the jobs that finished and exits with 130.

- A backward timestamp jump cannot happen inside one RTSP session, because ffmpeg's
  muxer refuses it. `pts_back` is therefore a session restart with an earlier clock.
- mediamtx answers `400` for paths it has no configuration for. The bench configures
  `nothing/...` as a never-published path so that a missing stream gets `404`, like a
  real camera does.

## Known findings

The synthetic run currently fails 5 scenarios. They are findings about the integration,
to be fixed separately; the bench is reporting them correctly. Until then the CI job and
its stages are `continue-on-error`.

- `lights_on`: missed. The whole-picture brightening is not detected.
- `glitch_burst`: 1 false alarm from the one-frame white glitches.
- `freeze_long`: `video_lost` never fires. `av.open` blocks while the session is open
  but silent, so `LOST_GRACE` never runs. (The `freeze_long` tests are strict xfails for
  the same reason.)
- `pts_back`: motion stays stuck after a restart with an earlier clock.
- `low_fps`: motion stuck, plus a 6 s delay at 2 fps.
- mediamtx answers `400` (not `404`) for paths it has no configuration for, and the
  integration maps only `404` to `stream_not_found`. The bench works around it with the
  `nothing/...` path.

## How scoring works

Times are seconds from the start of the run (the scoring origin).

- **Hit**: a motion starts in `[truth.start - 1.0, truth.end]`.
- **Delay**: motion start minus `truth.start`.
- **False alarm**: a motion with no truth interval within 2.0 s of it.
- **Stuck**: a motion that ends more than `hold + 2.0` s after the last truth end it
  overlaps, or never ends.
- **Miss**: a truth interval with no hit.

A synthetic row passes when: connected at least once, no misses, false alarms not
above the scenario's expected count (0), no stuck motion, and the number of
`video_lost` events equals the expected count (0, or 1 for `freeze_long`).

VIRAT rows are measurements: there is no pass or fail.

## VIRAT

[VIRAT Video Dataset Release 2.0](https://viratdata.org/) (Kitware) is a collection
of ground camera surveillance clips with object annotations. The bench can replay
a subset as RTSP streams to measure the detector on real footage.

**You must read and accept the VIRAT Video Dataset Usage Agreement yourself before
downloading anything.** It is here:

- https://data.kitware.com/api/v1/collection/56f56db28d777f753209ba9f (field `terms`)
- https://viratdata.org/

The bench never redistributes the data. This repository contains no VIRAT videos,
annotations or derived truth. They exist only in the Docker volume `virat-data`, on your
machine, after you download them. The download is opt-in:

```bash
docker compose -f bench/docker-compose.yml run --rm runner \
  python -m virat.fetch --accept-virat-terms --subset virat/subset.txt --dest /data/virat
```

`--accept-virat-terms` states that you have read and accepted the agreement. The subset
is 119 clips, about 4.3 GB. Then:

```bash
docker compose -f bench/docker-compose.yml run --rm runner python -m runner virat [--only CLIP] [--limit N] [--parallel N]
```

Truth is derived from the annotated object boxes: an object is moving when it travels
more than 2% of the frame width per second, and motion intervals are the union of
those. As a consequence, truth starts can be up to about 1 s late, and very slow
movers are ignored (the detector may report them, and they then count as false
alarms).

### Citation

If you use VIRAT results, cite the dataset:

> S. Oh, A. Hoogs, A. Perera, N. Cuntoor, C.-C. Chen, J. T. Lee, S. Mukherjee,
> J. K. Aggarwal, H. Lee, L. Davis, E. Swears, X. Wang, Q. Ji, K. Reddy, M. Shah,
> C. Vondrick, H. Pirsiavash, D. Ramanan, J. Yuen, A. Torralba, B. Song, A. Fong,
> A. Roy-Chowdhury, M. Desai, "A Large-scale Benchmark Dataset for Event Recognition
> in Surveillance Video", IEEE Conference on Computer Vision and Pattern Recognition
> (CVPR), 2011. VIRAT Video Dataset Release 2.0.

```bibtex
@inproceedings{oh2011virat,
  author    = {S. Oh and A. Hoogs and A. Perera and N. Cuntoor and C.-C. Chen and
               J. T. Lee and S. Mukherjee and J. K. Aggarwal and H. Lee and L. Davis and
               E. Swears and X. Wang and Q. Ji and K. Reddy and M. Shah and C. Vondrick and
               H. Pirsiavash and D. Ramanan and J. Yuen and A. Torralba and B. Song and
               A. Fong and A. Roy-Chowdhury and M. Desai},
  title     = {A Large-scale Benchmark Dataset for Event Recognition in Surveillance Video},
  booktitle = {IEEE Conference on Computer Vision and Pattern Recognition (CVPR)},
  year      = {2011},
  note      = {VIRAT Video Dataset Release 2.0}
}
```
