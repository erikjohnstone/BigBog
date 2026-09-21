"""N1 contract: the Niagara catalog and the static ``.bog`` validator.

Every ``.bog`` BACTalk produces must pass the validator, every known-bad fixture
must fail on exactly the rule it is named after, and the committed catalog must
match a fresh harvest of the vendored corpus (integration tier).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bactalk.agent import SequencePackPlanner
from bactalk.compiler import NiagaraCompiler
from bactalk.demo import standard_ahu_demo_job, standard_vav_demo_job
from bactalk.niagara.catalog import DOC_ONLY_ORIGIN, load_catalog
from bactalk.niagara.validate import BogValidationError, validate_bog
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService

pytestmark = [pytest.mark.minimal, pytest.mark.native_bog]

ROOT = Path(__file__).resolve().parents[1]
BAD = ROOT / "tests" / "fixtures" / "native-bog" / "bad"
BAD_FIXTURES = sorted(BAD.glob("*.bog"))

# pybog type per compiler block family, so the catalog is checked against what
# the compiler actually emits rather than against itself.
COMPILER_TYPES = {
    "control:NumericWritable": ("in16", "out"),
    "control:BooleanWritable": ("in16", "out"),
    "kitControl:NumericConst": ("out",),
    "kitControl:BooleanConst": ("out",),
    "kitControl:Add": ("inA", "inB", "out"),
    "kitControl:Subtract": ("inA", "inB", "out"),
    "kitControl:Multiply": ("inA", "inB", "out"),
    "kitControl:Divide": ("inA", "inB", "out"),
    "kitControl:Minimum": ("inA", "inB", "out"),
    "kitControl:Maximum": ("inA", "inB", "out"),
    "kitControl:Average": ("inA", "inB", "out"),
    "kitControl:GreaterThan": ("inA", "inB", "out"),
    "kitControl:GreaterThanEqual": ("inA", "inB", "out"),
    "kitControl:LessThan": ("inA", "inB", "out"),
    "kitControl:LessThanEqual": ("inA", "inB", "out"),
    "kitControl:Equal": ("inA", "inB", "out"),
    "kitControl:NotEqual": ("inA", "inB", "out"),
    "kitControl:And": ("inA", "inB", "out"),
    "kitControl:Or": ("inA", "inB", "out"),
    "kitControl:Xor": ("inA", "inB", "out"),
    "kitControl:Not": ("in", "out"),
    "kitControl:NumericSwitch": ("inSwitch", "inTrue", "inFalse", "out"),
    "kitControl:BooleanSwitch": ("inSwitch", "inTrue", "inFalse", "out"),
    "kitControl:BooleanDelay": ("in", "out"),
    "kitControl:OneShot": ("in", "out"),
    "kitControl:NumericLatch": ("in", "clock", "out"),
    "kitControl:BooleanLatch": ("in", "clock", "out"),
    "kitControl:Reset": (
        "inA",
        "inputLowLimit",
        "inputHighLimit",
        "outputLowLimit",
        "outputHighLimit",
        "out",
    ),
    "kitControl:LoopPoint": (
        "loopEnable",
        "controlledVariable",
        "setpoint",
        "loopAction",
        "out",
    ),
    "history:NumericIntervalHistoryExt": ("historyConfig",),
    "history:BooleanIntervalHistoryExt": ("historyConfig",),
    "schedule:BooleanSchedule": ("out",),
    "schedule:NumericSchedule": ("out",),
}


def _compile(tmp_path: Path, job) -> Path:
    graph = SequencePackPlanner().plan(job)
    path = tmp_path / f"{graph.name}.bog"
    NiagaraCompiler().compile(
        graph,
        path,
        deliverables=job.deliverables,
        units={point.name: point.units for point in job.points},
    )
    return path


def test_catalog_is_harvested_with_provenance() -> None:
    catalog = load_catalog()
    assert catalog.schema == "bactalk.niagara-catalog/v1"
    assert len(catalog.types) > 150
    harvested = [spec for spec in catalog.types.values() if spec.origin == "harvested"]
    assert all(spec.sources for spec in harvested), "every harvested type names its files"
    assert all(
        catalog.sources[source]["sha256"] for spec in harvested for source in spec.sources
    )
    # Symbols resolve to modules the corpus actually declares.
    assert catalog.symbols["b"] == "baja"
    assert catalog.symbols["c"] == "control"
    assert catalog.symbols["sch"] == "schedule"


def test_catalog_covers_every_type_and_slot_the_compiler_emits() -> None:
    catalog = load_catalog()
    missing = []
    for type_key, slots in COMPILER_TYPES.items():
        spec = catalog.get(type_key)
        if spec is None:
            missing.append(type_key)
            continue
        for slot in slots:
            if slot not in spec.slots:
                missing.append(f"{type_key}.{slot}")
    assert not missing, missing


def test_doc_only_entries_are_marked_and_cited() -> None:
    catalog = load_catalog()
    writable = catalog.types["control:NumericWritable"]
    assert writable.slots["in16"].origins[-1] == DOC_ONLY_ORIGIN
    assert writable.slots["in16"].data_kind == "numeric"
    assert writable.slots["in16"].link_target_seen > 0, "still harvested as a link target"
    assert writable.slots["in1"].origins == (DOC_ONLY_ORIGIN,)
    assert catalog.types["program:Program"].slots["execute"].slot_kind == "action"


@pytest.mark.parametrize("build", [standard_vav_demo_job, standard_ahu_demo_job])
def test_compiled_bog_passes_the_static_validator(tmp_path: Path, build) -> None:
    report = validate_bog(_compile(tmp_path, build()))
    assert report.ok, [str(issue) for issue in report.errors]
    assert report.component_count > 10 and report.link_count > 10
    assert not report.rules("warning") & {
        "link.source_not_output",
        "link.target_is_output",
        "link.source_external",
        "module.declared",
    }, [str(issue) for issue in report.warnings]


@pytest.mark.parametrize("fixture", BAD_FIXTURES, ids=[path.stem for path in BAD_FIXTURES])
def test_each_known_bad_fixture_fails_on_its_rule(fixture: Path) -> None:
    report = validate_bog(fixture)
    assert not report.ok, f"{fixture.name} was accepted"
    assert fixture.stem in report.rules("error"), [str(issue) for issue in report.errors]
    with pytest.raises(BogValidationError) as raised:
        report.raise_for_errors()
    assert fixture.stem in str(raised.value)


def test_every_rule_has_a_known_bad_fixture() -> None:
    documented = {
        "archive.structure",
        "xml.well_formed",
        "xml.root",
        "module.declared",
        "module.consistent",
        "type.known",
        "handle.well_formed",
        "handle.unique",
        "link.fields",
        "link.source_resolves",
        "link.source_slot",
        "link.target_slot",
        "link.double_driven",
        "link.kind_match",
        "facets.parse",
        "facets.unit_known",
    }
    assert {path.stem for path in BAD_FIXTURES} == documented


def test_service_refuses_a_bog_that_fails_validation(tmp_path: Path, monkeypatch) -> None:
    """The validator is wired into the run, not just available."""

    import bactalk.service as service_module

    original = service_module.validate_bog

    def poisoned(source, **kwargs):
        report = original(source, **kwargs)
        report.issues.append(
            type(report.issues[0])("type.known", "error", "/", "poisoned")
            if report.issues
            else __import__("bactalk.niagara.validate", fromlist=["Issue"]).Issue(
                "type.known", "error", "/", "poisoned"
            )
        )
        return report

    monkeypatch.setattr(service_module, "validate_bog", poisoned)
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    with pytest.raises(ValueError, match="static Niagara validation"):
        service.create_run(standard_vav_demo_job())


def test_service_records_the_validation_report(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(standard_vav_demo_job())
    assert record.bog_path is not None
    report_path = Path(record.bog_path).with_name("niagara-validation.json")
    assert report_path.is_file()
    assert '"ok": true' in report_path.read_text(encoding="utf-8")


@pytest.mark.integration
def test_committed_catalog_matches_a_fresh_harvest() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "harvest_niagara_catalog.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.integration
def test_every_vendored_bog_passes_the_validator() -> None:
    corpus = [
        *sorted((ROOT / ".vendor" / "n4-hvac-optimization-blocks").rglob("*.bog")),
        *sorted((ROOT / ".vendor" / "nhaystack").rglob("*.bog")),
    ]
    assert corpus, "vendored corpus is present"
    failures = {
        path.name: [str(issue) for issue in report.errors]
        for path in corpus
        if not (report := validate_bog(path)).ok
    }
    assert not failures, failures
