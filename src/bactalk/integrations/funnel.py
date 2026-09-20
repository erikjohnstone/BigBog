from __future__ import annotations

import csv
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


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
        with self.errors_csv.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or "y" not in reader.fieldnames:
                return ()
            values: list[float] = []
            for row in reader:
                try:
                    value = float(row["y"])
                except (KeyError, TypeError, ValueError):
                    return ()
                if not math.isfinite(value):
                    return ()
                values.append(value)
            return tuple(values)

    @property
    def passed(self) -> bool:
        errors = self.errors
        return self.completed and bool(errors) and all(value == 0.0 for value in errors)

    @property
    def max_error(self) -> float | None:
        errors = self.errors
        return max((abs(value) for value in errors), default=None)


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
        try:
            from pyfunnel import compareAndReport
        except ImportError as exc:  # pragma: no cover - installation guard
            raise RuntimeError("install BACTalk with the 'funnel' extra to use pyfunnel") from exc

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
