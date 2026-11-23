"""Run independent jobs N at a time. Generic: the virat command can reuse it."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

Job = tuple[str, Callable[[], dict]]


def run_jobs(jobs: list[Job], parallel: int = 1,
             on_row: Callable[[list[dict]], None] | None = None,
             on_done: Callable[[dict], None] | None = None) -> list[dict]:
    """Run (name, fn) jobs, at most `parallel` at once. Returns one row per job in
    job order. A job that raises yields a FAIL row with the error. on_row is called
    after each job finishes with the rows so far (in job order, finished ones only);
    on_done is called with the row of the job that just finished."""
    parallel = max(1, parallel)
    results: dict[int, dict] = {}

    def partial() -> list[dict]:
        return [results[i] for i in sorted(results)]

    def call(name: str, fn: Callable[[], dict]) -> dict:
        try:
            return fn()
        except Exception as err:  # noqa: BLE001 - one job must not lose the others
            return {"scenario": name, "passed": False, "error": f"{type(err).__name__}: {err}"}

    if parallel == 1:
        for i, (name, fn) in enumerate(jobs):
            results[i] = call(name, fn)
            if on_done:
                on_done(results[i])
            if on_row:
                on_row(partial())
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futs = {pool.submit(call, name, fn): i for i, (name, fn) in enumerate(jobs)}
            for fut in as_completed(futs):
                results[futs[fut]] = fut.result()
                if on_done:
                    on_done(results[futs[fut]])
                if on_row:
                    on_row(partial())
    return [results[i] for i in range(len(jobs))]
