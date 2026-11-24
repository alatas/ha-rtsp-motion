"""Run independent jobs N at a time. Generic: the synthetic and virat commands share it."""
from __future__ import annotations

from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Callable

Job = tuple[str, Callable[[], dict]]


def _call(name: str, fn: Callable[[], dict]) -> dict:
    """Module level so process pools can pickle it."""
    try:
        return fn()
    except Exception as err:  # noqa: BLE001 - one job must not lose the others
        return {"scenario": name, "passed": False, "error": f"{type(err).__name__}: {err}"}


def run_jobs(jobs: list[Job], parallel: int = 1,
             on_row: Callable[[list[dict]], None] | None = None,
             on_done: Callable[[dict], None] | None = None,
             order: list[int] | None = None,
             processes: bool = False) -> list[dict]:
    """Run (name, fn) jobs, at most `parallel` at once.

    Returns one row per job in job order (on Ctrl-C: KeyboardInterrupt with the
    finished rows in `.rows`). A job that raises yields a FAIL row with the error.
    `order` is the order jobs are started in (indexes into `jobs`, e.g. longest
    first); rows stay in job order. `processes` runs jobs in worker processes (for
    CPU-bound jobs; fn must be picklable, e.g. functools.partial of a module-level
    function). on_row is called after each job finishes with the rows so far (job
    order, finished ones only); on_done with the row of the job that just finished.
    """
    parallel = max(1, parallel)
    order = list(range(len(jobs))) if order is None else order
    results: dict[int, dict] = {}

    def partial() -> list[dict]:
        return [results[i] for i in sorted(results)]

    def finished(i: int, row: dict) -> None:
        results[i] = row
        if on_done:
            on_done(row)
        if on_row:
            on_row(partial())

    if parallel == 1 and not processes:
        try:
            for i in order:
                finished(i, _call(*jobs[i]))
        except KeyboardInterrupt as err:
            err.rows = partial()
            raise
        return [results[i] for i in range(len(jobs))]

    pool: Executor = (ProcessPoolExecutor if processes else ThreadPoolExecutor)(max_workers=parallel)
    try:
        # Pools start work in submission order, so `order` decides what runs first.
        futs = {pool.submit(_call, *jobs[i]): i for i in order}
        for fut in as_completed(futs):
            finished(futs[fut], fut.result())
    except KeyboardInterrupt as err:
        # Do not wait for queued jobs (the `with` form would). Running thread jobs
        # cannot be killed; the process exits after the caller reports.
        pool.shutdown(wait=False, cancel_futures=True)
        err.rows = partial()
        raise
    else:
        pool.shutdown()
    return [results[i] for i in range(len(jobs))]
