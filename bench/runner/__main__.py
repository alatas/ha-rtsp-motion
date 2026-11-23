import argparse
import os
import sys
import time

from fakecam.scenarios import SCENARIOS
from runner.report import write_report
from runner.parallel import run_jobs
from runner.run_detector import run_scenario

def results_path(name: str) -> str:
    """Output files go to $BENCH_RESULTS_DIR (default results/), so tests can redirect them."""
    return os.path.join(os.environ.get("BENCH_RESULTS_DIR", "results"), name)


MAX_PARALLEL = 6  # above this the on-demand publishers start late and timing skews


def virat_main(args) -> int:
    from runner import virat_run
    clips = virat_run.list_clips(args.only, args.limit)
    if not clips:
        print(virat_run.NO_DATA)
        return 0
    if args.parallel > MAX_PARALLEL:
        print(f"warning: --parallel {args.parallel} is above {MAX_PARALLEL}; timing skews",
              file=sys.stderr, flush=True)

    def save(rows: list[dict]) -> None:
        virat_run.write_virat_report(rows, results_path("virat.md"), results_path("virat.json"))

    def done(row: dict) -> None:
        print(f"{row['scenario']}: {'ok' if row['passed'] else 'ERROR'}"
              + (f" ({row['error']})" if row.get("error") else ""), flush=True)

    jobs = [(c, lambda c=c: virat_run.run_clip(c)) for c in clips]
    rows = run_jobs(jobs, args.parallel, on_row=save, on_done=done)
    save(rows)
    t = virat_run.totals(rows)
    print(f"{t['clips']} clips, hits {t['hits']}/{t['truth']}, false alarms {t['false_alarms']}, "
          f"stuck {t['stuck']}", flush=True)
    return 0  # measurements, not pass/fail


def main() -> int:
    ap = argparse.ArgumentParser(prog="runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    syn = sub.add_parser("synthetic")
    syn.add_argument("--only", help="run just this scenario")
    syn.add_argument("--parallel", type=int, default=1, metavar="N",
                     help="run up to N scenarios at the same time (default 1). Above 6 the "
                          "on-demand publishers start late and timing skews: see the connect "
                          "offset column")
    vir = sub.add_parser("virat", help="measure the detector on VIRAT clips (no pass/fail)")
    vir.add_argument("--only", help="run just this clip")
    vir.add_argument("--limit", type=int, metavar="N", help="run at most N clips")
    vir.add_argument("--parallel", type=int, default=1, metavar="N",
                     help="run up to N clips at the same time (default 1; above 6 timing skews)")
    args = ap.parse_args()
    if args.cmd == "virat" and args.limit is not None and args.limit < 1:
        ap.error("--limit must be >= 1")

    if args.parallel < 1:
        ap.error("--parallel must be >= 1")
    if args.cmd == "virat":
        return virat_main(args)
    names = [args.only] if args.only else [n for n in SCENARIOS if n != "static"]
    t0 = time.monotonic()

    if args.parallel > MAX_PARALLEL:
        print(f"warning: --parallel {args.parallel} is above {MAX_PARALLEL}; scenario timing "
              "skews under that load, so FAIL rows may be measurement artifacts",
              file=sys.stderr, flush=True)

    def save(rows: list[dict]) -> None:
        write_report(rows, results_path("synthetic.md"), results_path("synthetic.json"))

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
