"""VIRAT report: run the detector over real clips and measure (no pass/fail)."""
import json
import os
import statistics
from pathlib import Path

import av

from custom_components.rtsp_motion.detector import DetectorSettings
from runner.run_detector import BASE, run_stream, run_token, score_recording
from runner.report import write_report

NO_DATA = "No VIRAT data. Run: python -m virat.fetch --accept-virat-terms"
FOOTER = ("Truth comes from VIRAT object annotations (moving boxes only, > 2% of frame width "
          "per second); it starts up to ~1 s late and ignores very slow movers.")
EXTRA_SECONDS = 10


def data_dir() -> Path:
    return Path(os.environ.get("BENCH_VIRAT_DIR", "/data/virat"))


def list_clips(only: str | None = None, limit: int | None = None) -> list[str]:
    names = sorted(p.stem for p in (data_dir() / "truth").glob("*.json"))
    if only:
        names = [n for n in names if n == only]
    else:  # test fixtures (FAKE_*) run only when asked for by name
        names = [n for n in names if not n.startswith("FAKE_")]
    return names[:limit] if limit else names


def clip_seconds(clip: str) -> float:
    with av.open(str(data_dir() / "videos" / f"{clip}.mp4")) as c:
        if c.duration:
            return c.duration / av.time_base
        s = c.streams.video[0]
        return float(s.duration * s.time_base)


def run_clip(clip: str) -> dict:
    truth = json.loads((data_dir() / "truth" / f"{clip}.json").read_text())["truth"]
    settings = DetectorSettings()
    seconds = clip_seconds(clip) + EXTRA_SECONDS
    rec = run_stream(f"{BASE}/virat-once/{clip}/{run_token()}", settings, seconds)
    row = score_recording(clip, [tuple(t) for t in truth], rec, settings, seconds)
    row["passed"] = row["connected"] >= 1 and not row.get("error")  # a measurement: only a dead stream is an error
    if row["connected"] < 1:
        row["error"] = "never connected"
    return row


def totals(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("passed") and not r.get("error")]
    truth = sum(r.get("truth", 0) for r in ok)
    hits = sum(r.get("hits", 0) for r in ok)
    delays = [d for r in ok for d in r.get("delays", [])]
    secs = sum(r.get("run_seconds", 0.0) for r in ok)
    fa = sum(r.get("false_alarms", 0) for r in ok)
    return {"clips": len(rows), "errors": len(rows) - len(ok), "truth": truth, "hits": hits,
            "hit_rate": hits / truth if truth else None,
            "median_delay": statistics.median(delays) if delays else None,
            "false_alarms": fa, "run_seconds": secs,
            "false_alarms_per_hour": fa / (secs / 3600) if secs else None,
            "stuck": sum(r.get("stuck", 0) for r in ok)}


def _fmt(v, spec: str) -> str:
    return "-" if v is None else format(v, spec)


def write_virat_report(rows: list[dict], md_path: str, json_path: str) -> None:
    write_report(rows, md_path, json_path, labels=("ok", "ERROR"))
    t = totals(rows)
    md = Path(md_path).read_text()
    md += ("\n## Totals\n\n"
           f"- clips run: {t['clips']} ({t['errors']} errors, not counted below)\n"
           f"- truth intervals: {t['truth']}\n- hits: {t['hits']}\n"
           f"- hit rate: {_fmt(t['hit_rate'], '.1%')}\n"
           f"- median delay: {_fmt(t['median_delay'], '.2f')} s\n"
           f"- false alarms: {t['false_alarms']}\n"
           f"- false alarms per hour: {_fmt(t['false_alarms_per_hour'], '.2f')} "
           f"(over {t['run_seconds']:.0f} s of run time)\n"
           f"- stuck: {t['stuck']}\n\n{FOOTER}\n")
    Path(md_path).write_text(md)
    Path(json_path).write_text(json.dumps({"totals": t, "rows": rows}, indent=2))
