import argparse
import sys
import time

from fakecam.scenarios import SCENARIOS
from runner.report import write_report
from runner.parallel import run_jobs
from runner.run_detector import run_scenario


def main() -> int:
    ap = argparse.ArgumentParser(prog="runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    syn = sub.add_parser("synthetic")
    syn.add_argument("--only", help="run just this scenario")
    syn.add_argument("--parallel", type=int, default=1, metavar="N",
                     help="run up to N scenarios at the same time (default 1)")
    args = ap.parse_args()

    if args.parallel < 1:
        ap.error("--parallel must be >= 1")
    names = [args.only] if args.only else [n for n in SCENARIOS if n != "static"]
    t0 = time.monotonic()

    def save(rows: list[dict]) -> None:
        print(rows[-1]["scenario"], "done", flush=True)
        write_report(rows, "results/synthetic.md", "results/synthetic.json")

    jobs = [(n, lambda n=n: run_scenario(n)) for n in names]
    rows = run_jobs(jobs, args.parallel, on_row=save)
    write_report(rows, "results/synthetic.md", "results/synthetic.json")
    print(f"wall time {time.monotonic() - t0:.0f} s, parallel {args.parallel}", flush=True)
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
