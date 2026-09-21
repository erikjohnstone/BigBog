from __future__ import annotations

import csv
import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bactalk.optional_dependencies import PYFUNNEL


@dataclass(frozen=True)
class FunnelResult:
    status_code: int
    output_directory: Path
    errors_csv: Path

    @property
    def completed(self) -> bool:
        return self.status_code == 0 and self.errors_csv.is_file()

    @property
    def errors(self) -> tuple[float, ...]:
        """Return pyfunnel's retained point-wise y errors.

        pyfunnel's process status reports whether comparison and report
        generation completed.  It does not, by itself, mean the trajectory
        stayed inside the funnel, so callers must inspect ``errors.csv``.
        """

        if not self.completed:
            return ()
        return tuple(error for _, error in self.error_points)

    @property
    def error_points(self) -> tuple[tuple[float, float], ...]:
        """Return the finite ``(time, error)`` series retained by pyfunnel."""

        if not self.completed:
            return ()
        with self.errors_csv.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not {"x", "y"} <= set(reader.fieldnames):
                return ()
            values: list[tuple[float, float]] = []
            for row in reader:
                try:
                    point = (float(row["x"]), float(row["y"]))
                except (KeyError, TypeError, ValueError):
                    return ()
                if not all(math.isfinite(value) for value in point):
                    return ()
                values.append(point)
            return tuple(values)

    @property
    def passed(self) -> bool:
        errors = self.errors
        return self.completed and bool(errors) and all(value == 0.0 for value in errors)

    @property
    def max_error(self) -> float | None:
        errors = self.errors
        return max((abs(value) for value in errors), default=None)

    def counterexample(
        self,
        test_time: Sequence[float],
        test_values: Sequence[float],
        *,
        context_samples: int = 1,
    ) -> dict[str, object] | None:
        """Minimize a failed comparison to its violation span plus bounded context."""

        if self.passed:
            return None
        if len(test_time) != len(test_values) or not test_time:
            raise ValueError("counterexample test time and values must be nonempty and aligned")
        if context_samples < 0:
            raise ValueError("counterexample context_samples cannot be negative")
        times = [float(value) for value in test_time]
        values = [float(value) for value in test_values]
        if any(not math.isfinite(value) for value in [*times, *values]):
            raise ValueError("counterexample trajectory must contain only finite values")
        if any(
            current <= previous
            for previous, current in zip(times, times[1:], strict=False)
        ):
            raise ValueError("counterexample test time must be strictly increasing")
        violations = [(time, error) for time, error in self.error_points if error != 0.0]
        if not violations:
            return None

        def nearest_index(value: float) -> int:
            right = bisect_left(times, value)
            if right == 0:
                return 0
            if right == len(times):
                return len(times) - 1
            left = right - 1
            return left if abs(times[left] - value) <= abs(times[right] - value) else right

        first_index = nearest_index(violations[0][0])
        last_index = nearest_index(violations[-1][0])
        start_index = max(0, first_index - context_samples)
        end_index = min(len(times) - 1, last_index + context_samples)
        peak_time, peak_error = max(violations, key=lambda item: abs(item[1]))
        return {
            "schema": "bactalk.trajectory-counterexample/v1",
            "violation_count": len(violations),
            "first_violation_time": violations[0][0],
            "last_violation_time": violations[-1][0],
            "peak_error_time": peak_time,
            "peak_error": peak_error,
            "peak_absolute_error": abs(peak_error),
            "context_samples": context_samples,
            "window": {
                "start_index": start_index,
                "end_index": end_index,
                "test_times": times[start_index : end_index + 1],
                "test_values": values[start_index : end_index + 1],
            },
        }


class FunnelScorer:
    """Optional pyfunnel adapter for Tier-2 reference-trajectory scoring."""

    def compare(
        self,
        reference_time: Sequence[float],
        reference_values: Sequence[float],
        test_time: Sequence[float],
        test_values: Sequence[float],
        output_directory: Path,
        *,
        absolute_time_tolerance: float = 0.0,
        absolute_value_tolerance: float = 0.0,
    ) -> FunnelResult:
        # Raises OptionalDependencyError, which the API renders as a 503
        # naming this capability and the exact install command.
        PYFUNNEL.require()
        from pyfunnel import compareAndReport

        output_directory.mkdir(parents=True, exist_ok=True)
        status = compareAndReport(
            reference_time,
            reference_values,
            test_time,
            test_values,
            outputDirectory=str(output_directory),
            atolx=absolute_time_tolerance,
            atoly=absolute_value_tolerance,
        )
        return FunnelResult(
            status_code=int(status),
            output_directory=output_directory,
            errors_csv=output_directory / "errors.csv",
        )
