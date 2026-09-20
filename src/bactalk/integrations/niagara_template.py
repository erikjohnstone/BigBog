from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


class NiagaraTemplateAnalyzer:
    """Read-only template inspection built on pybog's Analyzer index."""

    def summarize(self, path: Path) -> dict[str, Any]:
        try:
            from bog_builder.analyzer import build_index, diagnose
        except ImportError as exc:  # pragma: no cover - installation guard
            raise RuntimeError("pybog is required for Niagara template analysis") from exc

        nodes = build_index(path, ignore_ws_annotations=False)
        diagnosis = diagnose(nodes)
        type_counts = Counter(node.key.type for node in nodes.values())
        return {
            "file": str(path.resolve()),
            "component_types": dict(sorted(type_counts.items())),
            "diagnosis": diagnosis,
        }

    def compare(self, baseline: Path, proposed: Path) -> dict[str, Any]:
        try:
            from bog_builder.analyzer import CompareOptions, compare
        except ImportError as exc:  # pragma: no cover - installation guard
            raise RuntimeError("pybog is required for Niagara template comparison") from exc

        report = compare(
            baseline,
            proposed,
            CompareOptions(ignore_handles=True, ignore_ws_annotations=True),
        )
        return {
            "added": [item.__dict__ for item in report.added],
            "removed": [item.__dict__ for item in report.removed],
            "modified": report.modified,
            "summary": report.summary,
            "problems_baseline": report.problems_left,
            "problems_proposed": report.problems_right,
        }
