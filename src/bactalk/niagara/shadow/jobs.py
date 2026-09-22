"""Fan-out of Shadow Runtime suites over many programs (N6 item 7).

``run_program_job`` is importable by an RQ worker (the same queue the
qualification jobs use); ``run_project_suite`` runs a list of programs through
a process pool locally or through any object with ``enqueue``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bactalk.domain import AcceptanceCase, TestReport
from bactalk.niagara.shadow.driver import ShadowRunOptions, run_shadow_suite
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, PLAUSIBLE_POLICIES

RQ_FUNCTION = "bactalk.niagara.shadow.jobs.run_program_job"


@dataclass(frozen=True)
class ProgramSuite:
    name: str
    bog_path: Path
    cases: tuple[AcceptanceCase, ...]
    sequence_family: str | None = None


def _policy(name: str):
    for policy in PLAUSIBLE_POLICIES:
        if policy.name == name:
            return policy
    if name == DEFAULT_POLICY.name:
        return DEFAULT_POLICY
    raise ValueError(f"unknown policy {name!r}")


def run_program_job(
    bog_path: str,
    cases_json: str,
    *,
    policy: str = DEFAULT_POLICY.name,
    kernel_backend: str = "auto",
    sequence_family: str | None = None,
) -> dict[str, Any]:
    """Worker entry point: one program, its cases as JSON; returns the report as JSON data."""

    cases = [AcceptanceCase.model_validate(item) for item in json.loads(cases_json)]
    options = ShadowRunOptions(
        policy=_policy(policy), kernel_backend=kernel_backend, sequence_family=sequence_family
    )
    report = run_shadow_suite(Path(bog_path), cases, options=options)
    return report.model_dump(mode="json")


def _run_one(item: tuple[str, str, str, str, str | None]) -> tuple[str, dict[str, Any]]:
    name, bog_path, cases_json, policy, backend = item[0], item[1], item[2], item[3], item[4]
    return name, run_program_job(
        bog_path, cases_json, policy=policy, kernel_backend=backend or "auto"
    )


def run_project_suite(
    programs: Sequence[ProgramSuite],
    *,
    policy: str = DEFAULT_POLICY.name,
    kernel_backend: str = "auto",
    max_workers: int | None = None,
    executor: Callable[
        [Sequence[tuple[str, str, str, str, str | None]]], list[tuple[str, dict[str, Any]]]
    ]
    | None = None,
) -> dict[str, TestReport]:
    """Run every program's suite in parallel; returns reports by program name."""

    items = [
        (
            program.name,
            str(program.bog_path),
            json.dumps([case.model_dump(mode="json") for case in program.cases]),
            policy,
            kernel_backend,
        )
        for program in programs
    ]
    if executor is not None:
        pairs = executor(items)
    else:
        workers = max_workers or max(1, min(len(items), os.cpu_count() or 1))
        if workers == 1 or len(items) == 1:
            pairs = [_run_one(item) for item in items]
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                pairs = list(pool.map(_run_one, items))
    return {name: TestReport.model_validate(data) for name, data in pairs}


def enqueue_project_suite(
    queue: Any,
    programs: Sequence[ProgramSuite],
    *,
    policy: str = DEFAULT_POLICY.name,
    kernel_backend: str = "auto",
) -> list[Any]:
    """Enqueue one worker job per program on an RQ-style queue (``queue.enqueue(func, ...)``)."""

    jobs = []
    for program in programs:
        cases_json = json.dumps([case.model_dump(mode="json") for case in program.cases])
        jobs.append(
            queue.enqueue(
                RQ_FUNCTION,
                str(program.bog_path),
                cases_json,
                policy=policy,
                kernel_backend=kernel_backend,
                sequence_family=program.sequence_family,
            )
        )
    return jobs


__all__ = [
    "RQ_FUNCTION",
    "ProgramSuite",
    "enqueue_project_suite",
    "run_program_job",
    "run_project_suite",
]
