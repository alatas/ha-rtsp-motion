"""Write scenario result rows as Markdown and JSON."""
import json
import os

COLUMNS = ["scenario", "truth", "hits", "misses", "false alarms", "stuck", "lost",
           "median delay", "result"]


def write_report(rows: list[dict], md_path: str, json_path: str) -> None:
    for p in (md_path, json_path):
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in rows:
        d = r.get("median_delay")
        lines.append("| " + " | ".join([
            str(r["scenario"]), str(r["truth"]), str(r["hits"]), str(r["misses"]),
            str(r["false_alarms"]), str(r["stuck"]), str(r["lost"]),
            "-" if d is None else f"{d:.2f}s", "PASS" if r["passed"] else "FAIL"]) + " |")
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2)
