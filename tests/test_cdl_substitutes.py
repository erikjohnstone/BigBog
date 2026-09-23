"""BACTalk's CDL substitutes compute what LBNL's equations compute (decision 016).

Each utility LBNL writes as Modelica equations or an algorithm is replaced, for the
Open Control Engine, by a CDL block diagram (``bactalk.integrations.cdl_substitutes``).
These tests run the engine on each substitute and compare every output, every tick,
with a reference written directly from LBNL's source: the ``initial()`` equation, the
``when`` clauses of ``TimerWithReset`` (host-tick reading: a when-clause does not fire
at initialization and fires on the evaluation its condition becomes true), the
``max``/``min`` equations and ``TrueArrayConditional``'s algorithm loop. The references
are independent of BACTalk's own kernels. The sequences are seeded and dense enough
to put events on consecutive ticks.
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.integration]

ROOT = Path(__file__).resolve().parents[1]
STEP = 10.0
TICKS = 60


@pytest.fixture(scope="module")
def library() -> Any:
    from bactalk.integrations.plant_controls_library import PlantControlsCdlLibrary

    if not (ROOT / ".vendor" / "open-control-engine").is_dir():
        pytest.skip("the Open Control Engine checkout is not installed")
    return PlantControlsCdlLibrary()


def _run(library: Any, controller: str, parameters: dict[str, Any], rows: list[dict]) -> list:
    result = library.execute(
        controller,
        samples=[{"time": STEP * tick, "inputs": row} for tick, row in enumerate(rows)],
        parameters=parameters,
    )
    assert result["runtime"] == "Open Control Engine"
    assert result["cdl_substitutes"] == [f"Buildings.Templates.Plants.Controls.{controller}"]
    labels = {port["id"]: port["label"] for port in result["interface"]["outputs"]}
    return [
        {labels[port]: cell["value"] for port, cell in row["outputs"].items()}
        for row in result["trace"]["trace"]
    ]


def _booleans(rng: random.Random, probability: float) -> list[bool]:
    value = False
    values = []
    for _ in range(TICKS):
        if rng.random() < probability:
            value = not value
        values.append(value)
    return values


@pytest.mark.parametrize("initial", [False, True])
def test_initialization(library: Any, initial: bool) -> None:
    u = _booleans(random.Random(1), 0.4)
    observed = _run(library, "Utilities.Initialization", {"yIni": initial}, [{"u": v} for v in u])
    # y = if initial() then yIni else u
    expected = [initial, *u[1:]]
    assert [row["y"] for row in observed] == expected


@pytest.mark.parametrize(("name", "reduce"), [("MultiMaxInteger", max), ("MultiMinInteger", min)])
def test_integer_reductions(library: Any, name: str, reduce: Any) -> None:
    rng = random.Random(2)
    rows = [{f"u__{i}": rng.randint(-9, 9) for i in range(1, 5)} for _ in range(TICKS)]
    observed = _run(library, f"Utilities.{name}", {"nin": 4}, rows)
    assert [row["y"] for row in observed] == [reduce(row.values()) for row in rows]


def _timer_with_reset(t: float, u: list[bool], reset: list[bool]) -> list[tuple[float, bool]]:
    """LBNL Utilities.TimerWithReset, read tick by tick from its equations."""

    outputs = []
    entry = 0.0
    passed = False
    for tick, (on, res) in enumerate(zip(u, reset, strict=True)):
        time = STEP * tick
        if tick == 0:
            entry = time  # initial equation: entryTime = time
            passed = t <= 0  # initial equation: passed = t <= 0
        elif (on and not u[tick - 1]) or (res and not reset[tick - 1]):  # when {u, reset}
            entry = time
            passed = on and t <= 0
        elif on and time >= entry + t:  # elsewhen u and time >= pre(entryTime) + t
            passed = True
        elif not on and u[tick - 1]:  # elsewhen not u
            passed = False
        outputs.append((time - entry if on else 0.0, passed))
    return outputs


@pytest.mark.parametrize(("threshold", "seed"), [(35.0, 3), (35.0, 4), (0.0, 5), (-10.0, 6)])
def test_timer_with_reset(library: Any, threshold: float, seed: int) -> None:
    rng = random.Random(seed)
    u = _booleans(rng, 0.3)
    reset = _booleans(rng, 0.35)
    observed = _run(
        library,
        "Utilities.TimerWithReset",
        {"t": threshold},
        [{"u": a, "reset": b} for a, b in zip(u, reset, strict=True)],
    )
    expected = _timer_with_reset(threshold, u, reset)
    assert [(row["y"], row["passed"]) for row in observed] == expected


def _true_array_conditional(count: int, indices: list[int], nout: int) -> list[bool]:
    """LBNL Utilities.TrueArrayConditional's algorithm, statement for statement."""

    y1 = [False] * nout
    true_count, position = 0, 1
    while true_count < count and position <= len(indices):
        if 1 <= indices[position - 1] <= nout:
            y1[indices[position - 1] - 1] = True
            true_count += 1
        position += 1
    return y1


@pytest.mark.parametrize(("nin", "nout"), [(3, 3), (4, 2)])
def test_true_array_conditional(library: Any, nin: int, nout: int) -> None:
    rng = random.Random(7 + nin)
    rows = []
    for _ in range(TICKS):
        row = {"u": rng.randint(-1, nin + 1)}
        # out-of-range and repeated indices included, as the algorithm allows them
        row.update({f"uIdx__{i}": rng.randint(0, nout + 1) for i in range(1, nin + 1)})
        rows.append(row)
    observed = _run(library, "Utilities.TrueArrayConditional", {"nin": nin, "nout": nout}, rows)
    for row, result in zip(rows, observed, strict=True):
        indices = [row[f"uIdx__{i}"] for i in range(1, nin + 1)]
        expected = _true_array_conditional(row["u"], indices, nout)
        assert [result[f"y1__{k}"] for k in range(1, nout + 1)] == expected, row


def test_committed_substitutes_match_a_fresh_translation() -> None:
    if not (ROOT / ".vendor" / "modelica-json" / "app.js").is_file():
        pytest.skip("modelica-json is not installed")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_cdl_substitutes.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr
