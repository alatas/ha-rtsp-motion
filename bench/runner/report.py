"""Write scenario result rows as Markdown and JSON."""
import json
import os
import statistics

SKEW_LIMIT = 0.5  # seconds from the run's median connect offset


def skewed(rows: list[dict]) -> set[int]:
    """Indexes of rows whose connect offset is far from the median: load skew."""
    offs = [r["connect_offset"] for r in rows if r.get("connect_offset") is not None]
    if len(offs) < 2:
        return set()
    med = statistics.median(offs)
    return {i for i, r in enumerate(rows) if r.get("connect_offset") is not None
            and abs(r["connect_offset"] - med) > SKEW_LIMIT}

COLUMNS = ["scenario", "truth", "hits", "misses", "false alarms", "stuck", "lost",
           "median delay", "fps", "connect offset", "result"]


def write_report(rows: list[dict], md_path: str, json_path: str) -> None:
    for p in (md_path, json_path):
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    skew = skewed(rows)
    for i, r in enumerate(rows):
        d = r.get("median_delay")
        lines.append("| " + " | ".join([
            str(r["scenario"]), str(r.get("truth", "-")), str(r.get("hits", "-")), str(r.get("misses", "-")),
            str(r.get("false_alarms", "-")), str(r.get("stuck", "-")), str(r.get("lost", "-")),
            "-" if d is None else f"{d:.2f}s",
            "-" if r.get("fps") is None else f"{r['fps']:.1f}",
            "-" if r.get("connect_offset") is None else f"{r['connect_offset']:.2f}s",
            ("PASS" if r["passed"] else "FAIL" + (" (error)" if r.get("error") else ""))
            + (" (timing skew)" if i in skew else "")]) + " |")
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2)
