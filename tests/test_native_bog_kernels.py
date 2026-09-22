"""N3 contract: the ``bactalkG36`` kernels, wrappers and registry.

Every kernel compiles and reproduces (a) the Open Control Engine golden traces
already pinned for the ProgramObject generator and (b) BACTalk's IR interpreter
on randomised input sequences. The component wrappers compile against the
``javax.baja`` stubs, and the Python registry, the wrappers' slots and
``module-include.xml`` agree. Needs ``javac``; CI installs a JDK.
"""

from __future__ import annotations

import math
import random
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.niagara.catalog import load_catalog
from bactalk.niagara.kernels import (
    COMPONENT_SOURCES,
    MODULE_ROOT,
    compile_components,
    compile_kernels,
    run_kernel,
)
from bactalk.niagara.lowering import LOWERING_MATRIX, TRUE_DELAY_MODULE, LoweringClass
from bactalk.niagara.module import CHANGE_MODES, COMPONENTS, COMPONENTS_BY_KIND, declared_types
from bactalk.niagara.validate import validate_bog
from bactalk.simulator import GraphInterpreter

pytestmark = [pytest.mark.native_bog]


@pytest.fixture(scope="module")
def kernel_classes(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return compile_kernels(tmp_path_factory.mktemp("kernels"))


# --- goldens (rows taken from tests/test_niagara_program_codegen.py) ---------


def test_pid_with_reset_matches_the_oce_golden(kernel_classes: Path) -> None:
    rows = [
        (0.0, 0.2, 0.0, 0.0, 0.184),
        (0.1, 0.22, 0.0, 0.0, 0.19140000000000001),
        (0.2, 0.95, 0.0, 0.0, 0.45),
        (0.30000000000000004, 0.18, 0.0, 1.0, 0.3065913580246914),
        (0.4, 0.18, 0.0, 1.0, 0.275),
        (0.5, -1.38, 0.0, 0.0, -0.2799999999999999),
        (0.6000000000000001, 1.1, 0.0, 0.0, 0.45),
        (0.7000000000000001, -0.4, 0.0, 1.0, 0.041622222222222394),
        (0.8, -0.4, 0.0, 1.0, 0.275),
        (0.9, 0.025, 0.0, 0.0, 0.3829166666666667),
    ]
    params = {
        "controllerType": "PI",
        "reverseActing": True,
        "k": 0.37,
        "ti": 0.3,
        "td": 0.1,
        "r": 1.0,
        "ni": 0.9,
        "nd": 10.0,
        "yMin": -0.35,
        "yMax": 0.45,
        "xiStart": 0.11,
        "ydStart": 0.0,
        "yReset": 0.275,
    }
    actual = run_kernel(kernel_classes, "PidWithReset", params, [row[:4] for row in rows])
    for value, row in zip(actual, rows, strict=True):
        assert math.isclose(float(value), row[-1], rel_tol=0.0, abs_tol=5e-16)


def test_trim_and_respond_matches_the_oce_golden(kernel_classes: Path) -> None:
    expected = [10.0] * 12 + [9.9, 9.9, 9.4, 9.4, 8.9, 8.9] + [10.0] * 5
    rows = []
    for timestamp in range(0, 1321, 60):
        requests = 6.0 if 840 <= timestamp < 1080 else 3.0 if 720 <= timestamp < 840 else 0.0
        device_on = not (1080 <= timestamp < 1260)
        rows.append((float(timestamp), requests, device_on))
    params = {
        "initialSetpoint": 10.0,
        "minimumSetpoint": 0.0,
        "maximumSetpoint": 20.0,
        "delaySeconds": 600.0,
        "samplePeriodSeconds": 120.0,
        "ignoredRequests": 2.0,
        "trimAmount": 0.1,
        "respondAmount": -0.2,
        "maximumResponse": -0.6,
    }
    actual = [float(value) for value in run_kernel(kernel_classes, "TrimAndRespond", params, rows)]
    assert actual == expected


def test_timer_matches_the_oce_golden(kernel_classes: Path) -> None:
    rows = [
        (0.0, True),
        (0.5, True),
        (1.0, True),
        (1.0, True),
        (1.5, False),
        (2.0, True),
        (2.5, True),
    ]
    actual = run_kernel(kernel_classes, "Timer", {"thresholdSeconds": 1.0}, rows)
    assert actual == [
        "0.0,false",
        "0.5,false",
        "1.0,true",
        "1.0,true",
        "0.0,false",
        "0.0,false",
        "0.5,false",
    ]


def test_discrete_kernels_match_the_independent_goldens(kernel_classes: Path) -> None:
    assert run_kernel(
        kernel_classes,
        "UnitDelay",
        {"samplePeriodSeconds": 2.0, "initial": -1.0},
        [(0, 10), (1, 11), (2, 20), (3, 30), (4, 40)],
    ) == ["-1.0", "-1.0", "10.0", "10.0", "20.0"]
    assert run_kernel(
        kernel_classes,
        "FirstOrderHold",
        {"samplePeriodSeconds": 2.0},
        [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5)],
    ) == ["0.0", "0.0", "0.0", "1.0", "2.0", "3.0"]


# --- differential against the IR interpreter ---------------------------------


def _graph(kind: BlockKind, config: dict, inputs: dict[str, BlockKind]) -> ControlGraph:
    blocks = [
        Block(
            id=f"in_{name}",
            kind=source_kind,
            label=name,
            config={"default": 0.0 if source_kind is BlockKind.NUMERIC_INPUT else False},
        )
        for name, source_kind in inputs.items()
    ]
    blocks.append(Block(id="k", kind=kind, label="kernel", config=config))
    links = [Link(source=f"in_{name}", target="k", target_slot=name) for name in inputs]
    return ControlGraph(name="KERNEL", blocks=blocks, links=links)


def _boolean_walk(rng: random.Random, length: int, flip: float) -> list[bool]:
    value = rng.random() < 0.5
    out = []
    for _ in range(length):
        if rng.random() < flip:
            value = not value
        out.append(value)
    return out


def _numeric_walk(rng: random.Random, length: int) -> list[float]:
    value = rng.uniform(-5, 5)
    out = []
    for _ in range(length):
        value += rng.uniform(-1.0, 1.0)
        out.append(round(value, 3))
    return out


Case = tuple[BlockKind, dict, dict[str, BlockKind], str, dict, tuple[str, ...]]

_CASES: list[Case] = [
    (
        BlockKind.BOOLEAN_DELAY,
        {
            "on_delay_seconds": 7.0,
            "delay_on_init": False,
            "semantic_contract": "CDL.Logical.TrueDelay",
        },
        {"in": BlockKind.BOOLEAN_INPUT},
        "TrueDelay",
        {"delaySeconds": 7.0, "delayOnInit": False},
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_DELAY,
        {
            "on_delay_seconds": 7.0,
            "delay_on_init": True,
            "semantic_contract": "CDL.Logical.TrueDelay",
        },
        {"in": BlockKind.BOOLEAN_INPUT},
        "TrueDelay",
        {"delaySeconds": 7.0, "delayOnInit": True},
        ("out",),
    ),
    (
        BlockKind.TIMER,
        {"threshold_seconds": 9.0, "semantic_contract": "CDL.Logical.Timer"},
        {"in": BlockKind.BOOLEAN_INPUT},
        "Timer",
        {"thresholdSeconds": 9.0},
        ("elapsed", "passed"),
    ),
    (
        BlockKind.TIMER_WITH_RESET,
        {"threshold_seconds": 9.0},
        {"in": BlockKind.BOOLEAN_INPUT, "reset": BlockKind.BOOLEAN_INPUT},
        "TimerWithReset",
        {"thresholdSeconds": 9.0},
        ("elapsed", "passed"),
    ),
    (
        BlockKind.TIMER_ACCUMULATING,
        {"threshold_seconds": 9.0},
        {"in": BlockKind.BOOLEAN_INPUT, "reset": BlockKind.BOOLEAN_INPUT},
        "TimerAccumulating",
        {"thresholdSeconds": 9.0},
        ("elapsed", "passed"),
    ),
    (
        BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
        {"true_hold_seconds": 6.0, "false_hold_seconds": 3.0},
        {"in": BlockKind.BOOLEAN_INPUT},
        "TrueFalseHold",
        {"trueHoldSeconds": 6.0, "falseHoldSeconds": 3.0},
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_PRE_HOST_TICK,
        {
            "initial": False,
            "semantic_contract": "CDL.Logical.Pre",
            "execution_profile": "host_tick_v1",
        },
        {"in": BlockKind.BOOLEAN_INPUT},
        "Pre",
        {"initial": False},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_UNIT_DELAY,
        {
            "sample_period_seconds": 4.0,
            "initial": 1.5,
            "semantic_contract": "CDL.Discrete.UnitDelay",
        },
        {"in": BlockKind.NUMERIC_INPUT},
        "UnitDelay",
        {"samplePeriodSeconds": 4.0, "initial": 1.5},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_FIRST_ORDER_HOLD,
        {"sample_period_seconds": 4.0, "semantic_contract": "CDL.Discrete.FirstOrderHold"},
        {"in": BlockKind.NUMERIC_INPUT},
        "FirstOrderHold",
        {"samplePeriodSeconds": 4.0},
        ("out",),
    ),
    (
        BlockKind.MOVING_AVERAGE,
        {"window_seconds": 10.0, "semantic_contract": "CDL.Reals.MovingAverage"},
        {"in": BlockKind.NUMERIC_INPUT},
        "MovingAverage",
        {"windowSeconds": 10.0},
        ("out",),
    ),
    (
        BlockKind.PID_WITH_RESET,
        {
            "controller_type": "PI",
            "k": 0.37,
            "ti": 3.0,
            "td": 0.1,
            "r": 1.0,
            "ni": 0.9,
            "nd": 10.0,
            "y_min": -0.35,
            "y_max": 0.45,
            "xi_start": 0.11,
            "yd_start": 0.0,
            "y_reset": 0.275,
            "reverse_acting": True,
        },
        {
            "setpoint": BlockKind.NUMERIC_INPUT,
            "measurement": BlockKind.NUMERIC_INPUT,
            "trigger": BlockKind.BOOLEAN_INPUT,
        },
        "PidWithReset",
        {
            "controllerType": "PI",
            "reverseActing": True,
            "k": 0.37,
            "ti": 3.0,
            "td": 0.1,
            "r": 1.0,
            "ni": 0.9,
            "nd": 10.0,
            "yMin": -0.35,
            "yMax": 0.45,
            "xiStart": 0.11,
            "ydStart": 0.0,
            "yReset": 0.275,
        },
        ("out",),
    ),
    (
        BlockKind.TRIM_AND_RESPOND,
        {
            "initial_setpoint": 10.0,
            "minimum_setpoint": 5.0,
            "maximum_setpoint": 15.0,
            "delay_seconds": 6.0,
            "sample_period_seconds": 4.0,
            "ignored_requests": 2.0,
            "trim_amount": -0.1,
            "respond_amount": 0.2,
            "maximum_response": 0.6,
            "hold_enabled": False,
        },
        {"request_count": BlockKind.NUMERIC_INPUT, "device_on": BlockKind.BOOLEAN_INPUT},
        "TrimAndRespond",
        {
            "initialSetpoint": 10.0,
            "minimumSetpoint": 5.0,
            "maximumSetpoint": 15.0,
            "delaySeconds": 6.0,
            "samplePeriodSeconds": 4.0,
            "ignoredRequests": 2.0,
            "trimAmount": -0.1,
            "respondAmount": 0.2,
            "maximumResponse": 0.6,
        },
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_INITIALIZATION,
        {
            "initial": True,
            "semantic_contract": "Buildings.Templates.Plants.Controls.Utilities.Initialization",
        },
        {"in": BlockKind.BOOLEAN_INPUT},
        "BooleanInitialization",
        {"initial": True},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_CHANGED,
        {"initial": 0.0},
        {"in": BlockKind.NUMERIC_INPUT},
        "NumericChange",
        {"mode": "changed", "initial": 0.0},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_INCREASED,
        {"initial": 0.0},
        {"in": BlockKind.NUMERIC_INPUT},
        "NumericChange",
        {"mode": "increased", "initial": 0.0},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_DECREASED,
        {"initial": 0.0},
        {"in": BlockKind.NUMERIC_INPUT},
        "NumericChange",
        {"mode": "decreased", "initial": 0.0},
        ("out",),
    ),
    (
        BlockKind.ONE_SHOT,
        {"initial": False},
        {"in": BlockKind.BOOLEAN_INPUT},
        "RisingEdge",
        {"initial": False},
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_FALLING_EDGE,
        {"pre_u_start": True},
        {"in": BlockKind.BOOLEAN_INPUT},
        "FallingEdge",
        {"initial": True},
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_SET_RESET,
        {},
        {"set": BlockKind.BOOLEAN_INPUT, "clear": BlockKind.BOOLEAN_INPUT},
        "SetReset",
        {},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_SAMPLER,
        {"sample_period_seconds": 4.0},
        {"in": BlockKind.NUMERIC_INPUT},
        "Sampler",
        {"samplePeriodSeconds": 4.0},
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_SAMPLE_TRIGGER,
        {"period_seconds": 4.0, "shift_seconds": 1.0},
        {},
        "SampleTrigger",
        {"periodSeconds": 4.0, "shiftSeconds": 1.0},
        ("out",),
    ),
    (
        BlockKind.HYSTERESIS,
        {"u_low": -1.0, "u_high": 1.0, "initial": False},
        {"in": BlockKind.NUMERIC_INPUT},
        "Hysteresis",
        {"uLow": -1.0, "uHigh": 1.0, "initial": False},
        ("out",),
    ),
]


def _format(value: float | bool) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else repr(float(value))


def _close(actual: str, expected: float | bool) -> bool:
    if isinstance(expected, bool):
        return actual == ("true" if expected else "false")
    return math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9)


@pytest.mark.parametrize("case", _CASES, ids=[f"{c[0].value}-{c[3]}" for c in _CASES])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_kernel_matches_the_ir_interpreter(kernel_classes: Path, case: Case, seed: int) -> None:
    kind, config, inputs, kernel, params, outputs = case
    rng = random.Random(seed * 1000 + hash(kind.value) % 1000)
    length = 60
    series: dict[str, list[float | bool]] = {}
    for name, source_kind in inputs.items():
        if source_kind is BlockKind.BOOLEAN_INPUT:
            series[name] = list(_boolean_walk(rng, length, flip=0.2))
        else:
            series[name] = list(_numeric_walk(rng, length))
    steps = [rng.choice([0.5, 1.0, 1.0, 2.0, 3.0]) for _ in range(length)]

    interpreter = GraphInterpreter(_graph(kind, config, inputs))
    expected: list[list[float | bool]] = []
    rows: list[list[float | bool]] = []
    for index in range(length):
        values = interpreter.evaluate(
            {f"in_{name}": series[name][index] for name in inputs},
            step_seconds=steps[index],
        )
        expected.append([values[f"k.{slot}"] for slot in outputs])
        rows.append([interpreter.time, *(series[name][index] for name in inputs)])

    actual = run_kernel(kernel_classes, kernel, params, rows)
    assert len(actual) == length
    for index, (line, wanted) in enumerate(zip(actual, expected, strict=True)):
        cells = line.split(",")
        assert len(cells) == len(wanted)
        for slot, cell, value in zip(outputs, cells, wanted, strict=True):
            assert _close(cell, value), (
                f"{kernel}.{slot} at row {index} (t={rows[index][0]}): "
                f"kernel {cell} vs interpreter {_format(value)}"
            )


# --- wrappers, registry and descriptors ----------------------------------------


def test_component_wrappers_compile_against_the_stubs(tmp_path: Path) -> None:
    classes = compile_components(tmp_path / "components")
    compiled = {path.stem for path in (classes / "com" / "bactalk" / "g36").glob("B*.class")}
    assert {Path(component.java_class).name for component in COMPONENTS} <= compiled


_PROPERTY = re.compile(r"public static final Property (\w+) =\s*newProperty\(")


def _wrapper_slots(java_class: str) -> set[str]:
    source = (MODULE_ROOT / "bactalkG36-rt" / "src" / f"{java_class}.java").read_text("utf-8")
    return set(_PROPERTY.findall(source))


def test_registry_slots_match_the_java_wrappers() -> None:
    base = set(_PROPERTY.findall((COMPONENT_SOURCES / "BKernelComponent.java").read_text("utf-8")))
    assert base == {"executionPeriod"}
    for component in COMPONENTS:
        own = {slot for slot, _, _ in component.slots}
        assert own == _wrapper_slots(component.java_class), component.name
        declared = own | base
        for binding in component.bindings:
            assert binding.property in declared, (component.name, binding.property)
        for slot in component.input_map.values():
            assert slot in declared, (component.name, slot)
        for slot in component.output_map.values():
            assert slot in declared, (component.name, slot)


def test_module_include_lists_exactly_the_registry() -> None:
    root = ElementTree.parse(MODULE_ROOT / "bactalkG36-rt" / "module-include.xml").getroot()
    listed = {element.get("name"): element.get("class") for element in root.iter("type")}
    assert listed == {
        component.name: component.java_class.replace("/", ".") for component in COMPONENTS
    }


def test_registry_covers_every_module_row_of_the_matrix() -> None:
    module_kinds = {
        decision.kind
        for decision in LOWERING_MATRIX.values()
        if decision.lowering is LoweringClass.MODULE
    } | {TRUE_DELAY_MODULE.kind}
    assert module_kinds == set(COMPONENTS_BY_KIND)
    for decision in LOWERING_MATRIX.values():
        if decision.lowering is LoweringClass.MODULE:
            assert COMPONENTS_BY_KIND[decision.kind].type_key == decision.target, decision.kind
    assert COMPONENTS_BY_KIND[BlockKind.BOOLEAN_DELAY].type_key == TRUE_DELAY_MODULE.target
    assert set(CHANGE_MODES) == set(COMPONENTS_BY_KIND[BlockKind.NUMERIC_CHANGED].kinds)


def test_declared_types_are_accepted_by_the_validator() -> None:
    catalog = load_catalog().with_types(declared_types())
    assert "bactalkG36:TrueDelay" in catalog
    palette = MODULE_ROOT / "bactalkG36-wb" / "module.palette"
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("file.xml", palette.read_bytes())
    report = validate_bog(buffer.getvalue(), declared_types=declared_types(), label="palette")
    assert report.ok, [str(issue) for issue in report.errors]
    rejected = validate_bog(buffer.getvalue(), label="palette-without-module")
    assert "type.known" in rejected.rules("error")
