"""N7: the Gate G-WB calibration kit builds, runs, compares and annotates."""

from __future__ import annotations

import csv
import io
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bactalk.niagara.calibration import (
    CALIBRATIONS,
    CALIBRATIONS_BY_ID,
    COVERED_BY,
    ExpectedTrace,
    Step,
    annotate_document,
    compare_evidence,
    compare_trace,
    expected_traces,
    parse_history_export,
    write_kit,
)
from bactalk.niagara.shadow.status import Status
from bactalk.niagara.validate import validate_bog

pytestmark = [pytest.mark.native_bog]

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "calibration"
DOC = ROOT / "docs" / "niagara-semantics.md"


def _assumed_rules() -> set[str]:
    rules = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| (S-[A-Z0-9-]+) \| .* \| (ASSUMED[^|]*) \|", line)
        if match:
            rules.add(match.group(1))
    return rules


def test_every_assumed_rule_has_a_calibration() -> None:
    covered = set(CALIBRATIONS_BY_ID) | set(COVERED_BY)
    assumed = _assumed_rules()
    assert assumed, "the semantics document lists no ASSUMED rule"
    assert assumed <= covered, sorted(assumed - covered)
    assert covered <= assumed, sorted(covered - assumed)
    for rule, by in COVERED_BY.items():
        assert by in CALIBRATIONS_BY_ID, f"{rule} covered by unknown calibration {by}"


@pytest.mark.parametrize("calibration", CALIBRATIONS, ids=lambda c: c.id)
def test_kit_program_validates_and_produces_expected_traces(calibration) -> None:
    content = calibration.build()
    report = validate_bog(content, label=calibration.folder)
    assert report.errors == [], [issue.message for issue in report.errors]
    traces = expected_traces(calibration, content=content)
    assert [trace.point for trace in traces] == list(calibration.observe)
    for trace in traces:
        times = [record[0] for record in trace.records]
        assert times, f"{calibration.id}/{trace.point} recorded nothing"
        assert times[0] == pytest.approx(1.0), "records start one interval after start"
        assert times[-1] == pytest.approx(calibration.duration_seconds)
        assert all(b - a == pytest.approx(1.0) for a, b in zip(times, times[1:], strict=False))
        assert ExpectedTrace.from_csv(calibration.id, trace.point, trace.to_csv()).records == [
            (t, v, s) for t, v, s in trace.records
        ]


def test_committed_kit_matches_the_code(tmp_path: Path) -> None:
    """``scripts/build_calibration_kit.py --check`` in test form."""

    fresh = tmp_path / "calibration"
    written = write_kit(fresh)
    assert len(written) == len(list(KIT.rglob("*.*")))
    for path in written:
        committed = KIT / path.relative_to(fresh)
        assert committed.is_file(), f"{committed} missing; run scripts/build_calibration_kit.py"
        assert committed.read_bytes() == path.read_bytes(), (
            f"{committed} is stale; run scripts/build_calibration_kit.py"
        )


def test_kit_readme_names_every_calibration_and_step() -> None:
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    for calibration in CALIBRATIONS:
        assert f"`{calibration.folder}/`" in readme
        for step in calibration.steps:
            assert step.describe() in readme


def _station_export(trace: ExpectedTrace, *, perturb: float = 0.0) -> str:
    """Render an expected trace as a Niagara-style history export."""

    origin = datetime(2026, 9, 22, 9, 0, 0, tzinfo=UTC)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Timestamp", "Trend Flags", "Status", "Value"])
    for time_seconds, value, status in trace.records:
        stamp = (origin + timedelta(seconds=time_seconds - trace.records[0][0])).strftime(
            "%d-%b-%y %I:%M:%S %p UTC"
        )
        shown = value
        if perturb and not isinstance(value, bool) and time_seconds > 5:
            shown = float(value) + perturb
        status_text = (
            "{null}" if status & Status.NULL else ("{fault}" if status & Status.FAULT else "{ok}")
        )
        writer.writerow([stamp, "{}", status_text, str(shown).lower()])
    return buffer.getvalue()


def _write_evidence(root: Path, *, perturb_id: str | None = None) -> None:
    for calibration in CALIBRATIONS:
        if not calibration.station_testable:
            continue
        folder = root / calibration.folder
        folder.mkdir(parents=True)
        for point in calibration.observe:
            trace = ExpectedTrace.from_csv(
                calibration.id,
                point,
                (KIT / calibration.folder / f"expected-{point}.csv").read_text(encoding="utf-8"),
            )
            perturb = 1.0 if calibration.id == perturb_id else 0.0
            (folder / f"{point}.csv").write_text(_station_export(trace, perturb=perturb))


def test_parse_history_export_reads_niagara_timestamps() -> None:
    text = (
        "Timestamp,Trend Flags,Status,Value\n"
        "22-Sep-26 09:00:01 AM UTC,{},{ok},5.0\n"
        "22-Sep-26 09:00:02 AM UTC,{},{ok},5.0\n"
        "22-Sep-26 09:00:03 AM UTC,{},{null},true\n"
    )
    rows = parse_history_export(text)
    assert [row[0] for row in rows] == [0.0, 1.0, 2.0]
    assert rows[0][1] == 5.0 and rows[2][1] is True
    assert rows[2][2] == "{null}"


def test_compare_trace_flags_value_time_and_status_mismatches() -> None:
    expected = ExpectedTrace("X", "p", [(1.0, 5.0, 0), (2.0, 5.0, 0), (3.0, 2.0, 0x40)])
    assert (
        compare_trace(expected, [(0.0, 5.0, "{ok}"), (1.0, 5.0, "{ok}"), (2.0, 2.0, "{null}")])
        == []
    )
    assert compare_trace(expected, []) == ["no records exported"]
    assert any(
        "expected 2.0" in m
        for m in compare_trace(expected, [(0.0, 5.0, None), (1.0, 5.0, None), (2.0, 3.0, None)])
    )
    assert any(
        "status" in m
        for m in compare_trace(
            expected, [(0.0, 5.0, "{ok}"), (1.0, 5.0, "{ok}"), (2.0, 2.0, "{ok}")]
        )
    )
    assert any("no station record" in m for m in compare_trace(expected, [(0.0, 5.0, None)]))


def test_matching_evidence_verifies_and_perturbed_evidence_contradicts(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _write_evidence(evidence, perturb_id="S-MATH-2")
    shutil.rmtree(evidence / CALIBRATIONS_BY_ID["S-CMP-1"].folder)
    verdicts = {v.assumption: v for v in compare_evidence(evidence, KIT)}
    assert set(verdicts) == set(CALIBRATIONS_BY_ID)
    assert verdicts["S-MATH-2"].status == "CONTRADICTED"
    assert verdicts["S-MATH-2"].mismatches
    assert verdicts["S-CMP-1"].status == "MISSING"
    for calibration in CALIBRATIONS:
        if calibration.id in {"S-MATH-2", "S-CMP-1"}:
            continue
        expected = "VERIFIED" if calibration.station_testable else "NOT_TESTABLE"
        assert verdicts[calibration.id].status == expected, (
            calibration.id,
            verdicts[calibration.id],
        )


def test_annotate_document_marks_covered_rules_and_is_idempotent(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _write_evidence(evidence, perturb_id="S-MATH-2")
    verdicts = compare_evidence(evidence, KIT)
    document = tmp_path / "niagara-semantics.md"
    document.write_text(DOC.read_text(encoding="utf-8"), encoding="utf-8")
    changed = annotate_document(document, verdicts, today="2026-09-22")
    testable = {c.id for c in CALIBRATIONS if c.station_testable}
    testable |= {rule for rule, by in COVERED_BY.items() if by in testable}
    assert changed == len(testable)
    text = document.read_text(encoding="utf-8")
    assert re.search(r"^\| S-MATH-2 \| .* → CONTRADICTED \(G-WB 2026-09-22\) \|", text, re.M)
    assert re.search(r"^\| S-STATUS-4 \| .* → VERIFIED \(G-WB 2026-09-22\) \|", text, re.M)
    assert re.search(r"^\| S-LOGIC-2 \| .* → VERIFIED \(G-WB 2026-09-22\) \|", text, re.M), (
        "covered rule"
    )
    again = annotate_document(document, verdicts, today="2026-09-23")
    assert again == changed
    assert "2026-09-22" not in document.read_text(encoding="utf-8")


def test_committed_document_carries_no_contradicted_rule() -> None:
    """Gate G-WB has not run; the doc must not claim a verdict either way."""

    text = DOC.read_text(encoding="utf-8")
    assert "CONTRADICTED (G-WB" not in text
    assert "VERIFIED (G-WB" not in text


def test_step_describe_is_operator_readable() -> None:
    assert Step(10.0, "override", "a", 3.0).describe() == "t=10s: override Inputs/a to 3.0"
    assert Step(0.0, "auto", "b").describe() == "t=0s: auto Inputs/b (remove the override)"
