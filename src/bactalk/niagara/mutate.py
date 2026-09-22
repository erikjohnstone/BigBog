"""Mutation testing for exported ``.bog`` files (GOAL-NATIVE-BOG.md N7, D4).

A mutant is the exported file with one deliberate defect: a link moved to another
slot, a block type changed, a link deleted, a constant altered, a loop action
reversed, a facet dropped or a writable's priority level changed. A mutant is
*caught* when the static validator rejects it, the Shadow Runtime refuses to load
it, or the job's acceptance suite fails against it. The catch rate over all
mutants is D4's measure; survivors are listed for review.
"""

from __future__ import annotations

import io
import random
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

from bactalk.domain import AcceptanceCase, JobSpec, TestReport
from bactalk.niagara.differential import three_way_differential
from bactalk.niagara.module import declared_types
from bactalk.niagara.shadow.driver import ShadowRunOptions, run_shadow_case, run_shadow_suite
from bactalk.niagara.shadow.loader import ShadowLoadError
from bactalk.niagara.validate import validate_bog
from bactalk.simulator import run_acceptance_suite

OPERATORS: tuple[str, ...] = (
    "swap_link_slot",
    "change_block_type",
    "delete_link",
    "alter_constant",
    "flip_loop_action",
    "drop_facets",
    "change_priority_level",
    "invert_parameter",
)

# Same-arity replacements that stay statically valid, so the mutant reaches the runtime.
_TYPE_SWAPS: dict[str, str] = {
    "kitControl:Add": "kitControl:Subtract",
    "kitControl:Subtract": "kitControl:Add",
    "kitControl:Multiply": "kitControl:Divide",
    "kitControl:Minimum": "kitControl:Maximum",
    "kitControl:Maximum": "kitControl:Minimum",
    "kitControl:GreaterThan": "kitControl:LessThan",
    "kitControl:LessThan": "kitControl:GreaterThan",
    "kitControl:GreaterThanEqual": "kitControl:LessThanEqual",
    "kitControl:LessThanEqual": "kitControl:GreaterThanEqual",
    "kitControl:Equal": "kitControl:NotEqual",
    "kitControl:NotEqual": "kitControl:Equal",
    "kitControl:And": "kitControl:Or",
    "kitControl:Or": "kitControl:And",
    "kitControl:Xor": "kitControl:Or",
    "kitControl:Not": "kitControl:And",
    "bactalkG36:RisingEdge": "bactalkG36:FallingEdge",
    "bactalkG36:FallingEdge": "bactalkG36:RisingEdge",
    "bactalkG36:Timer": "bactalkG36:TimerAccumulating",
}
_SLOT_SWAPS: dict[str, tuple[str, ...]] = {
    "inA": ("inB",),
    "inB": ("inA",),
    "inTrue": ("inFalse",),
    "inFalse": ("inTrue",),
    "setpoint": ("measurement",),
    "measurement": ("setpoint",),
    "set": ("clear",),
    "clear": ("set",),
}
_NUMERIC_PARAMS = (
    "k",
    "ti",
    "yMin",
    "yMax",
    "trimAmount",
    "respondAmount",
    "ignoredRequests",
    "uLow",
    "uHigh",
    "minimumSetpoint",
    "maximumSetpoint",
    "initialSetpoint",
)
_TIME_PARAMS = (
    "delayTime",
    "threshold",
    "samplePeriod",
    "trueHoldTime",
    "falseHoldTime",
    "window",
    "period",
    "onDelay",
    "offDelay",
    "delaySeconds",
)


@dataclass(frozen=True)
class Mutation:
    operator: str
    path: str
    detail: str
    index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "path": self.path,
            "detail": self.detail,
            "index": self.index,
        }


@dataclass
class Mutant:
    mutation: Mutation
    content: bytes


@dataclass
class MutantOutcome:
    mutation: Mutation
    caught_by: str | None
    """``validator``, ``loader``, ``suite``, ``differential`` or None when it survived."""

    detail: str = ""

    @property
    def caught(self) -> bool:
        return self.caught_by is not None

    def to_dict(self) -> dict[str, Any]:
        return {**self.mutation.to_dict(), "caught_by": self.caught_by, "detail": self.detail}


@dataclass
class MutationReport:
    total: int
    outcomes: list[MutantOutcome] = field(default_factory=list)

    @property
    def caught(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.caught)

    @property
    def catch_rate(self) -> float:
        return self.caught / self.total if self.total else 1.0

    @property
    def survivors(self) -> list[MutantOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.caught]

    def to_dict(self) -> dict[str, Any]:
        by_operator: dict[str, dict[str, int]] = {}
        for outcome in self.outcomes:
            entry = by_operator.setdefault(outcome.mutation.operator, {"total": 0, "caught": 0})
            entry["total"] += 1
            entry["caught"] += int(outcome.caught)
        by_catcher: dict[str, int] = {}
        for outcome in self.outcomes:
            by_catcher[outcome.caught_by or "survived"] = (
                by_catcher.get(outcome.caught_by or "survived", 0) + 1
            )
        return {
            "schema": "bactalk.bog-mutation/v1",
            "total": self.total,
            "caught": self.caught,
            "catch_rate": round(self.catch_rate, 4),
            "by_operator": by_operator,
            "by_catcher": by_catcher,
            "survivors": [outcome.to_dict() for outcome in self.survivors],
        }


# --- generating mutants ---------------------------------------------------------------------


def _read_xml(content: bytes) -> ElementTree.Element:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return ElementTree.fromstring(archive.read("file.xml"))


def _write_xml(root: ElementTree.Element) -> bytes:
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(root, encoding="utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file.xml", xml)
    return buffer.getvalue()


def _top(root: ElementTree.Element) -> ElementTree.Element:
    """The single top-level ``<p>`` (an UnrestrictedFolder); component paths start below it."""

    return next(child for child in root if child.tag == "p")


def _components(root: ElementTree.Element) -> list[tuple[str, ElementTree.Element]]:
    found: list[tuple[str, ElementTree.Element]] = []

    def walk(element: ElementTree.Element, path: str) -> None:
        for child in element:
            if child.tag != "p":
                continue
            name = child.get("n") or ""
            child_path = f"{path}/{name}"
            if child.get("h") is not None:
                found.append((child_path, child))
            walk(child, child_path)

    walk(_top(root), "")
    return found


def _links(root: ElementTree.Element) -> list[tuple[str, ElementTree.Element, ElementTree.Element]]:
    result = []
    for path, component in _components(root):
        for child in component:
            if child.tag == "p" and child.get("t") == "b:Link":
                result.append((f"{path}/{child.get('n')}", component, child))
    return result


def _field(link: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((c for c in link if c.get("n") == name), None)


def _resolve_type(raw: str) -> str:
    symbol, _, name = raw.partition(":")
    return {"b": "baja", "c": "control"}.get(symbol, symbol) + ":" + name


def generate_mutants(
    content: bytes, *, seed: int = 0, limit: int | None = None, operators: Iterable[str] = OPERATORS
) -> list[Mutant]:
    """Every applicable single-defect mutant of ``content`` (shuffled, capped at ``limit``)."""

    rng = random.Random(seed)
    wanted = set(operators)
    mutants: list[Mutant] = []
    base = _read_xml(content)
    components = _components(base)
    links = _links(base)
    index = 0

    def emit(operator: str, path: str, detail: str, mutate) -> None:
        nonlocal index
        root = _read_xml(content)
        mutate(root)
        mutants.append(Mutant(Mutation(operator, path, detail, index), _write_xml(root)))
        index += 1

    if "swap_link_slot" in wanted:
        for link_path, _, link in links:
            target = _field(link, "targetSlotName")
            if target is None:
                continue
            for replacement in _SLOT_SWAPS.get(target.get("v") or "", ()):
                # A driven sibling slot makes the validator catch it, which counts too.
                emit(
                    "swap_link_slot",
                    link_path,
                    f"targetSlotName {target.get('v')} -> {replacement}",
                    _swap_slot(link_path, replacement),
                )
    if "change_block_type" in wanted:
        for path, component in components:
            replacement = _TYPE_SWAPS.get(_resolve_type(component.get("t") or ""))
            if replacement:
                emit(
                    "change_block_type",
                    path,
                    f"{component.get('t')} -> {replacement}",
                    _set_type(path, replacement),
                )
    if "delete_link" in wanted:
        for link_path, _, _ in links:
            emit("delete_link", link_path, "link removed", _delete_link(link_path))
    if "alter_constant" in wanted:
        for path, component in components:
            if _resolve_type(component.get("t") or "") in {
                "kitControl:NumericConst",
                "control:NumericWritable",
            }:
                prop = next(
                    (
                        c
                        for c in component
                        if c.get("n") in {"out", "fallback"} and c.get("t") in {"b:StatusNumeric"}
                    ),
                    None,
                )
                value = _field(prop, "value") if prop is not None else None
                if value is None or value.get("v") is None:
                    continue
                current = float(value.get("v"))
                altered = current * 1.5 if current != 0.0 else 1.0
                emit(
                    "alter_constant",
                    path,
                    f"{prop.get('n')} {current} -> {altered}",
                    _set_status_value(path, prop.get("n"), altered),
                )
    if "flip_loop_action" in wanted:
        for path, component in components:
            kind = _resolve_type(component.get("t") or "")
            if kind == "kitControl:LoopPoint":
                emit(
                    "flip_loop_action",
                    path,
                    "loopAction reversed",
                    _set_or_add(
                        path,
                        "loopAction",
                        "kitControl:LoopAction",
                        "reverse",
                        flip={"direct": "reverse", "reverse": "direct"},
                    ),
                )
            elif kind == "bactalkG36:PIDWithReset":
                emit(
                    "flip_loop_action",
                    path,
                    "reverseActing flipped",
                    _flip_boolean(path, "reverseActing"),
                )
    if "drop_facets" in wanted:
        for path, component in components:
            if any(c.get("n") == "facets" for c in component):
                emit("drop_facets", path, "facets removed", _remove_prop(path, "facets"))
    if "change_priority_level" in wanted:
        for link_path, target, link in links:
            slot = _field(link, "targetSlotName")
            if (
                slot is not None
                and slot.get("v") == "in16"
                and _resolve_type(target.get("t") or "").startswith("control:")
            ):
                emit(
                    "change_priority_level",
                    link_path,
                    "in16 -> in1 (emergency level)",
                    _swap_slot(link_path, "in1"),
                )
    if "invert_parameter" in wanted:
        for path, component in components:
            for prop in component:
                name = prop.get("n") or ""
                if (
                    name in _NUMERIC_PARAMS
                    and prop.get("t") == "b:Double"
                    and prop.get("v") not in (None, "0.0")
                ):
                    emit(
                        "invert_parameter", path, f"{name} negated", _scale_double(path, name, -1.0)
                    )
                    break
                if (
                    name in _TIME_PARAMS
                    and prop.get("t") == "b:RelTime"
                    and prop.get("v") not in (None, "0")
                ):
                    emit(
                        "invert_parameter", path, f"{name} doubled", _scale_reltime(path, name, 2.0)
                    )
                    break
    rng.shuffle(mutants)
    if limit is not None:
        mutants = mutants[:limit]
    return mutants


def _find(root: ElementTree.Element, path: str) -> ElementTree.Element | None:
    element = _top(root)
    for segment in [s for s in path.split("/") if s]:
        element = next((c for c in element if c.tag == "p" and c.get("n") == segment), None)  # type: ignore[assignment]
        if element is None:
            return None
    return element


def _swap_slot(link_path: str, replacement: str):
    def mutate(root: ElementTree.Element) -> None:
        link = _find(root, link_path)
        assert link is not None
        _field(link, "targetSlotName").set("v", replacement)  # type: ignore[union-attr]

    return mutate


def _set_type(path: str, replacement: str):
    def mutate(root: ElementTree.Element) -> None:
        component = _find(root, path)
        assert component is not None
        symbol = (component.get("t") or "").partition(":")[0]
        module, _, name = replacement.partition(":")
        component.set(
            "t",
            f"{symbol}:{name}"
            if {"b": "baja", "c": "control"}.get(symbol, symbol) == module
            else replacement,
        )

    return mutate


def _delete_link(link_path: str):
    def mutate(root: ElementTree.Element) -> None:
        parent = _find(root, link_path.rsplit("/", 1)[0])
        link = _find(root, link_path)
        assert parent is not None and link is not None
        parent.remove(link)

    return mutate


def _set_status_value(path: str, prop_name: str, value: float):
    def mutate(root: ElementTree.Element) -> None:
        component = _find(root, path)
        assert component is not None
        prop = next(c for c in component if c.get("n") == prop_name)
        _field(prop, "value").set("v", repr(float(value)))  # type: ignore[union-attr]

    return mutate


def _set_or_add(
    path: str, name: str, type_spec: str, value: str, *, flip: dict[str, str] | None = None
):
    def mutate(root: ElementTree.Element) -> None:
        component = _find(root, path)
        assert component is not None
        prop = next((c for c in component if c.get("n") == name), None)
        if prop is None:
            ElementTree.SubElement(component, "p", {"n": name, "t": type_spec, "v": value})
        else:
            current = prop.get("v") or ""
            prop.set("v", (flip or {}).get(current.lower(), value))

    return mutate


def _flip_boolean(path: str, name: str):
    def mutate(root: ElementTree.Element) -> None:
        component = _find(root, path)
        assert component is not None
        prop = next((c for c in component if c.get("n") == name), None)
        if prop is None:
            ElementTree.SubElement(component, "p", {"n": name, "t": "b:Boolean", "v": "true"})
        else:
            prop.set("v", "false" if (prop.get("v") or "").lower() == "true" else "true")

    return mutate


def _remove_prop(path: str, name: str):
    def mutate(root: ElementTree.Element) -> None:
        component = _find(root, path)
        assert component is not None
        for prop in [c for c in component if c.get("n") == name]:
            component.remove(prop)

    return mutate


def _scale_double(path: str, name: str, factor: float):
    def mutate(root: ElementTree.Element) -> None:
        component = _find(root, path)
        assert component is not None
        prop = next(c for c in component if c.get("n") == name)
        prop.set("v", repr(float(prop.get("v") or 0.0) * factor))

    return mutate


def _scale_reltime(path: str, name: str, factor: float):
    def mutate(root: ElementTree.Element) -> None:
        component = _find(root, path)
        assert component is not None
        prop = next(c for c in component if c.get("n") == name)
        prop.set("v", str(int(round(float(prop.get("v") or 0) * factor))))

    return mutate


# --- judging mutants ------------------------------------------------------------------------


def judge_mutant(
    content: bytes,
    cases: Sequence[AcceptanceCase],
    *,
    kernel_backend: str = "python",
    job: JobSpec | None = None,
    reference: Mapping[str, Any] | None = None,
    interpreter_report: TestReport | None = None,
) -> tuple[str | None, str]:
    """(caught_by, detail) for one mutant, cheapest oracle first.

    ``validator`` (static), ``loader`` (the Shadow Runtime refuses the file), ``suite``
    (an acceptance expectation fails; scenarios stop at the first failure) and, when
    ``job`` is given, ``differential`` (D3: the mutant's output trajectories leave the
    documented bands around the interpreter and the reference on some scenario). The
    last is the oracle that matters: a mutation that no end-of-scenario expectation
    notices still changes what the controller does over time.
    """

    report = validate_bog(content, declared_types=declared_types())
    if not report.ok:
        return "validator", "; ".join(str(issue) for issue in report.errors[:3])
    family = job.sequence.family if job is not None else None
    options = ShadowRunOptions(
        kernel_backend=kernel_backend, record_internals=False, sequence_family=family
    )
    try:
        for case in cases:
            result, _ = run_shadow_case(content, case, options=options)
            if not result.passed:
                failing = next(a for a in result.assertions if not a.passed)
                return (
                    "suite",
                    f"{failing.name}: observed {failing.observed}, expected {failing.expected}",
                )
        if job is not None:
            shadow_report = run_shadow_suite(content, cases, options=options)
            differential = three_way_differential(
                job,
                bog=content,
                reference=reference,
                kernel_backend=kernel_backend,
                shadow_report=shadow_report,
                interpreter_report=interpreter_report,
            )
            failing_case = next((c for c in differential.cases if not c.passed), None)
            if failing_case is not None:
                return "differential", f"{failing_case.name}: {failing_case.first_divergence}"
    except (ShadowLoadError, ValueError, KeyError, TypeError) as exc:
        return "loader", f"{type(exc).__name__}: {exc}"
    return None, "every scenario still passes"


def _judge_serialised(
    item: tuple[bytes, list[dict[str, Any]], str, dict[str, Any] | None],
) -> tuple[str | None, str]:
    content, cases_json, backend, oracle = item
    cases = [AcceptanceCase.model_validate(case) for case in cases_json]
    if oracle is None:
        return judge_mutant(content, cases, kernel_backend=backend)
    return judge_mutant(
        content,
        cases,
        kernel_backend=backend,
        job=JobSpec.model_validate(oracle["job"]),
        reference=oracle["reference"],
        interpreter_report=TestReport.model_validate(oracle["interpreter_report"]),
    )


def run_mutation_suite(
    content: bytes,
    cases: Sequence[AcceptanceCase],
    *,
    seed: int = 0,
    limit: int | None = None,
    operators: Iterable[str] = OPERATORS,
    kernel_backend: str = "python",
    max_workers: int | None = None,
    job: JobSpec | None = None,
    reference: Mapping[str, Any] | None = None,
) -> MutationReport:
    """Generate mutants and judge each; parallel through a process pool.

    With ``job`` the D3 differential joins the oracles: the interpreter runs the
    suite once here and every mutant's Shadow Runtime trajectories are compared with
    it (and with ``reference`` when given) inside the documented bands.
    """

    mutants = generate_mutants(content, seed=seed, limit=limit, operators=operators)
    report = MutationReport(total=len(mutants))
    payload = [case.model_dump(mode="json") for case in cases]
    oracle: dict[str, Any] | None = None
    if job is not None:
        if job.control_graph is None:
            raise ValueError("the job carries no control graph")
        interpreter_report = run_acceptance_suite(job.control_graph, job)
        if not interpreter_report.passed:
            # A failing baseline would make every mutant look "caught by the suite".
            failing = [
                f"{scenario.name}: {assertion.name}"
                for scenario in interpreter_report.scenarios
                for assertion in scenario.assertions
                if not assertion.passed
            ]
            raise ValueError(
                "the unmutated graph fails its own acceptance suite, so the catch rate "
                "would be meaningless: " + "; ".join(failing[:3])
            )
        oracle = {
            "job": job.model_dump(mode="json"),
            "reference": dict(reference) if reference is not None else None,
            "interpreter_report": interpreter_report.model_dump(mode="json"),
        }
    baseline, detail = _judge_serialised((content, payload, kernel_backend, oracle))
    if baseline is not None:
        raise ValueError(
            f"the unmutated .bog is already caught by the {baseline} oracle ({detail}); "
            "the catch rate would be meaningless"
        )
    items = [(mutant.content, payload, kernel_backend, oracle) for mutant in mutants]
    if max_workers == 1 or len(items) <= 1:
        verdicts = [_judge_serialised(item) for item in items]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            verdicts = list(pool.map(_judge_serialised, items))
    for mutant, (caught_by, detail) in zip(mutants, verdicts, strict=True):
        report.outcomes.append(MutantOutcome(mutant.mutation, caught_by, detail))
    return report


__all__ = [
    "OPERATORS",
    "Mutant",
    "MutantOutcome",
    "Mutation",
    "MutationReport",
    "generate_mutants",
    "judge_mutant",
    "run_mutation_suite",
]
