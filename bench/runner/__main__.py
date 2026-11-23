import argparse
import sys

from fakecam.scenarios import SCENARIOS
from runner.report import write_report
from runner.run_detector import run_scenario


def main() -> int:
    ap = argparse.ArgumentParser(prog="runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    syn = sub.add_parser("synthetic")
    syn.add_argument("--only", help="run just this scenario")
    args = ap.parse_args()

    names = [args.only] if args.only else [n for n in SCENARIOS if n != "static"]
    rows = []
    for n in names:
        row = run_scenario(n)  # one at a time: one camera connection
        print(row, flush=True)
        rows.append(row)
        write_report(rows, "results/synthetic.md", "results/synthetic.json")
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
