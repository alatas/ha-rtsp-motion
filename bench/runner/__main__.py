import argparse
import sys
import time

from fakecam.scenarios import SCENARIOS
from runner.report import write_report
from runner.parallel import run_jobs
from runner.run_detector import run_scenario

MAX_PARALLEL = 6  # above this the on-demand publishers start late and timing skews


def main() -> int:
    ap = argparse.ArgumentParser(prog="runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    syn = sub.add_parser("synthetic")
    syn.add_argument("--only", help="run just this scenario")
    syn.add_argument("--parallel", type=int, default=1, metavar="N",
                     help="run up to N scenarios at the same time (default 1). Above 6 the "
                          "on-demand publishers start late and timing skews: see the connect "
                          "offset column")
    args = ap.parse_args()

    if args.parallel < 1:
        ap.error("--parallel must be >= 1")
    names = [args.only] if args.only else [n for n in SCENARIOS if n != "static"]
    t0 = time.monotonic()

    if args.parallel > MAX_PARALLEL:
        print(f"warning: --parallel {args.parallel} is above {MAX_PARALLEL}; scenario timing "
              "skews under that load, so FAIL rows may be measurement artifacts",
              file=sys.stderr, flush=True)

    def save(rows: list[dict]) -> None:
        write_report(rows, "results/synthetic.md", "results/synthetic.json")

    def done(row: dict) -> None:
        keys = ("misses", "false_alarms", "stuck", "lost", "error")
        detail = ", ".join(f"{k} {row[k]}" for k in keys if row.get(k))
        print(f"{row['scenario']}: {'PASS' if row['passed'] else 'FAIL'}"
              + (f" ({detail})" if detail else ""), flush=True)

    jobs = [(n, lambda n=n: run_scenario(n)) for n in names]
    rows = run_jobs(jobs, args.parallel, on_row=save, on_done=done)
    print(f"wall time {time.monotonic() - t0:.0f} s, parallel {args.parallel}", flush=True)
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
