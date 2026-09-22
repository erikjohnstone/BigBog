"""Java kernels versus Python ports on the same rows (docs/decisions/007).

Every kernel is driven through both implementations with random input walks at
irregular steps (including repeated instants, which exercise the same-instant
sampling rule); any difference in any output fails. ``python -m
bactalk.niagara.shadow check`` runs this; the test suite runs it when a JDK is
present.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from bactalk.niagara.shadow.kernels import build_kernel
from bactalk.niagara.shadow.sidecar import KernelSidecar, sidecar_available

# (kernel, params, input kinds) — the parameter names KernelHarness accepts.
KERNEL_CASES: tuple[tuple[str, dict[str, object], tuple[str, ...]], ...] = (
    ("TrueDelay", {"delaySeconds": 7.0, "delayOnInit": False}, ("b",)),
    ("TrueDelay", {"delaySeconds": 7.0, "delayOnInit": True}, ("b",)),
    ("Timer", {"thresholdSeconds": 9.0}, ("b",)),
    ("TimerWithReset", {"thresholdSeconds": 9.0}, ("b", "b")),
    ("TimerAccumulating", {"thresholdSeconds": 9.0}, ("b", "b")),
    ("TrueFalseHold", {"trueHoldSeconds": 6.0, "falseHoldSeconds": 3.0}, ("b",)),
    ("Pre", {"initial": False}, ("b",)),
    ("UnitDelay", {"samplePeriodSeconds": 4.0, "initial": 1.5}, ("n",)),
    ("FirstOrderHold", {"samplePeriodSeconds": 4.0}, ("n",)),
    ("MovingAverage", {"windowSeconds": 10.0}, ("n",)),
    ("MovingAverage", {"windowSeconds": 300.0}, ("n",)),
    (
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
        ("n", "n", "b"),
    ),
    (
        "PidWithReset",
        {
            "controllerType": "PID",
            "reverseActing": False,
            "k": 0.5,
            "ti": 2.0,
            "td": 0.4,
            "yMin": 0.0,
            "yMax": 1.0,
        },
        ("n", "n", "b"),
    ),
    (
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
        ("n", "b", "b"),
    ),
    (
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
            "holdEnabled": True,
            "holdDurationSeconds": 12.0,
        },
        ("n", "b", "b"),
    ),
    ("BooleanInitialization", {"initial": True}, ("b",)),
    ("NumericChange", {"mode": "changed", "initial": 0.0}, ("n",)),
    ("NumericChange", {"mode": "increased", "initial": 0.0}, ("n",)),
    ("NumericChange", {"mode": "decreased", "initial": 0.0}, ("n",)),
    ("RisingEdge", {"initial": False}, ("b",)),
    ("FallingEdge", {"initial": True}, ("b",)),
    ("SetReset", {}, ("b", "b")),
    ("Sampler", {"samplePeriodSeconds": 4.0}, ("n",)),
    ("SampleTrigger", {"periodSeconds": 4.0, "shiftSeconds": 1.0}, ()),
    ("Hysteresis", {"uLow": -1.0, "uHigh": 1.0, "initial": False}, ("n",)),
)


def random_rows(
    kinds: Sequence[str], seed: int, length: int = 80
) -> list[tuple[float, list[float | bool]]]:
    rng = random.Random(seed)
    time_seconds = 0.0
    numeric = {index: rng.uniform(-5, 5) for index, kind in enumerate(kinds) if kind == "n"}
    boolean = {index: rng.random() < 0.5 for index, kind in enumerate(kinds) if kind == "b"}
    rows = []
    for _ in range(length):
        step = rng.choice([0.0, 0.5, 1.0, 1.0, 2.0, 3.0, 4.0])
        time_seconds = round(time_seconds + step, 6)
        inputs: list[float | bool] = []
        for index, kind in enumerate(kinds):
            if kind == "n":
                numeric[index] = round(numeric[index] + rng.uniform(-1.0, 1.0), 3)
                inputs.append(numeric[index])
            else:
                if rng.random() < 0.2:
                    boolean[index] = not boolean[index]
                inputs.append(boolean[index])
        rows.append((time_seconds, inputs))
    return rows


@dataclass
class EquivalenceOutcome:
    checked: int = 0
    mismatches: list[str] = field(default_factory=list)
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return not self.mismatches and self.skipped is None

    def summary(self) -> str:
        if self.skipped:
            return f"skipped: {self.skipped}"
        if self.mismatches:
            return f"{len(self.mismatches)} mismatches over {self.checked} rows:\n" + "\n".join(
                self.mismatches[:20]
            )
        return f"python ports and java kernels agree on {self.checked} rows"


def _equal(a: float | bool, b: float | bool) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if math.isnan(float(a)) and math.isnan(float(b)):
        return True
    return float(a) == float(b)


def check_kernel_equivalence(seeds: Sequence[int] = (1, 2, 3)) -> EquivalenceOutcome:
    outcome = EquivalenceOutcome()
    if not sidecar_available():
        outcome.skipped = "javac/java not found"
        return outcome
    with KernelSidecar() as sidecar:
        for kernel, params, kinds in KERNEL_CASES:
            for seed in seeds:
                port = build_kernel(kernel, dict(params))
                ident = sidecar.open(kernel, params)
                for row_index, (time_seconds, inputs) in enumerate(random_rows(kinds, seed)):
                    expected = sidecar.step(ident, time_seconds, inputs)
                    actual = port.step(time_seconds, *inputs)
                    outcome.checked += 1
                    if len(expected) != len(actual) or not all(
                        _equal(a, b) for a, b in zip(actual, expected, strict=True)
                    ):
                        outcome.mismatches.append(
                            f"{kernel} {params} seed {seed} row {row_index} t={time_seconds}: "
                            f"java={expected} python={actual}"
                        )
                        break
                sidecar.close_kernel(ident)
    return outcome


__all__ = ["KERNEL_CASES", "EquivalenceOutcome", "check_kernel_equivalence", "random_rows"]
