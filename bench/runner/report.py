"""Write scenario result rows as Markdown and JSON."""
import json
import os

COLUMNS = ["scenario", "truth", "hits", "misses", "false alarms", "stuck", "lost",
           "median delay", "fps", "result"]


def write_report(rows: list[dict], md_path: str, json_path: str) -> None:
    for p in (md_path, json_path):
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in rows:
        d = r.get("median_delay")
        lines.append("| " + " | ".join([
            str(r["scenario"]), str(r.get("truth", "-")), str(r.get("hits", "-")), str(r.get("misses", "-")),
            str(r.get("false_alarms", "-")), str(r.get("stuck", "-")), str(r.get("lost", "-")),
            "-" if d is None else f"{d:.2f}s",
            "-" if r.get("fps") is None else f"{r['fps']:.1f}", ("PASS" if r["passed"] else "FAIL" + (" (error)" if r.get("error") else ""))]) + " |")
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2)
