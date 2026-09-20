from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    RunStatus,
    SequenceSpec,
)
from bactalk.integrations.boptest import BoptestClient
from bactalk.integrations.boptest_graph import (
    BoptestActuatorBinding,
    BoptestGraphMap,
    BoptestMeasurementBinding,
    BoptestTrajectoryOracle,
)
from bactalk.repository import RunRepository
from bactalk.service import ApprovalRequiredError, WorkbenchService


def fan_controller() -> ControlGraph:
    return ControlGraph(
        name="BoptestFanController",
        metadata={
            "purpose": "real closed-loop BACTalk IR to BOPTEST qualification",
            "threshold_kelvin": 292.0,
        },
        blocks=[
            Block(
                id="room_temp",
                kind=BlockKind.NUMERIC_INPUT,
                label="Room temperature",
                config={"default": 293.15},
            ),
            Block(
                id="threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Cooling threshold",
                config={"value": 292.0},
            ),
            Block(id="is_hot", kind=BlockKind.GREATER_THAN, label="Cooling request"),
            Block(
                id="fan_on",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan on",
                config={"value": 1.0},
            ),
            Block(
                id="fan_off",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan off",
                config={"value": 0.0},
            ),
            Block(id="select_fan", kind=BlockKind.NUMERIC_SWITCH, label="Fan selector"),
            Block(id="fan_command", kind=BlockKind.NUMERIC_OUTPUT, label="Fan command"),
        ],
        links=[
            Link(source="room_temp", target="is_hot", target_slot="a"),
            Link(source="threshold", target="is_hot", target_slot="b"),
            Link(source="is_hot", target="select_fan", target_slot="selector"),
            Link(source="fan_on", target="select_fan", target_slot="when_true"),
            Link(source="fan_off", target="select_fan", target_slot="when_false"),
            Link(source="select_fan", target="fan_command", target_slot="in"),
        ],
    )


def contractor_job() -> JobSpec:
    return JobSpec(
        name="BOPTEST contractor qualification job",
        site="BACTalk isolated simulation lab",
        equipment_name="FCU_BOPTEST_1",
        sequence=SequenceSpec(
            family="CUSTOM_FAN",
            version="Contractor-authored threshold control v1",
        ),
        points=[
            PointSpec(
                name="room_temp",
                label="Room temperature",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                units="K",
                default=293.15,
            ),
            PointSpec(
                name="fan_command",
                label="Fan command",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                units="%",
                default=0.0,
            ),
        ],
        control_graph=fan_controller(),
        acceptance_tests=[
            AcceptanceCase(
                name="hot room starts fan",
                inputs={"room_temp": 293.15},
                expectations=[OutputExpectation(target="fan_command", value=1.0)],
            )
        ],
        notes=(
            "Executable integration proof only. The generated BOG is not licensed-Niagara "
            "runtime-qualified and is not authorized for live-building deployment."
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a typed BACTalk controller against the real BOPTEST bestest_air FMU"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--step", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".bactalk/boptest-graph-runtime-evidence.json"),
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path(".bactalk/boptest-contractor-runs"),
    )
    arguments = parser.parse_args()

    mapping = BoptestGraphMap(
        test_case="bestest_air",
        measurements=[
            BoptestMeasurementBinding(
                graph_input="room_temp",
                measurement="zon_reaTRooAir_y",
            )
        ],
        actuators=[
            BoptestActuatorBinding(
                graph_output="fan_command",
                actuator="fcu_oveFan_u",
                activation_actuator="fcu_oveFan_activate",
            )
        ],
    )
    reference_times = [arguments.step * (index + 1) for index in range(arguments.steps)]
    oracle = BoptestTrajectoryOracle(
        id="fan-command-enabled",
        signal_kind="graph_output",
        signal="fan_command",
        reference_times=reference_times,
        reference_values=[1.0] * arguments.steps,
        absolute_value_tolerance=0.0,
    )
    service = WorkbenchService(RunRepository(arguments.run_root))
    candidate = service.create_run(
        contractor_job(),
        source_documents={
            "qualification-purpose.txt": (
                b"Real BOPTEST closed-loop contractor job integration proof.\n"
            )
        },
    )
    preapproval_export_denied = False
    try:
        service.export_path(candidate.id)
    except ApprovalRequiredError:
        preapproval_export_denied = True
    if not preapproval_export_denied:
        raise SystemExit("candidate exported before approval")

    with BoptestClient(arguments.base_url, timeout=60.0) as client:
        qualified = service.qualify_with_boptest(
            candidate.id,
            client=client,
            mapping=mapping,
            oracles=[oracle],
            steps=arguments.steps,
            step_seconds=arguments.step,
        )
    if qualified.status != RunStatus.READY_FOR_REVIEW:
        raise SystemExit("BOPTEST trajectory oracle failed")
    evidence = json.loads(Path(qualified.boptest_verification_path).read_text())
    trajectory = evidence["runtime"]["trajectory"]
    room_temperatures = [
        float(row["measurements"]["zon_reaTRooAir_y"]) for row in trajectory
    ]
    if len(set(room_temperatures)) <= 1:
        raise SystemExit("BOPTEST room temperature did not respond across the trajectory")

    approved = service.approve(candidate.id, "BACTalk Integration Test Reviewer")
    exported = service.export_path(candidate.id)
    review_bundle = service.review_bundle_path(candidate.id)
    with zipfile.ZipFile(review_bundle) as archive:
        bundle_entries = archive.namelist()
    if "boptest-verification/evidence.json" not in bundle_entries:
        raise SystemExit("review bundle omitted signed BOPTEST evidence")

    retained = {
        "schema": "bactalk.boptest-contractor-e2e/v1",
        "status": "pass",
        "run_id": approved.id,
        "workflow": [
            "contractor_job_created",
            "deterministic_acceptance_tests_passed",
            "niagara_bog_generated",
            "preapproval_export_denied",
            "real_boptest_closed_loop_passed",
            "pyfunnel_oracle_passed",
            "simulation_evidence_bound_to_artifact_digest",
            "test_identity_approved",
            "approved_bog_and_review_bundle_exported",
        ],
        "candidate_artifact_sha256": candidate.artifact_sha256,
        "qualified_artifact_sha256": qualified.artifact_sha256,
        "qualification_changed_digest": (
            candidate.artifact_sha256 != qualified.artifact_sha256
        ),
        "preapproval_export_denied": preapproval_export_denied,
        "qualification_evidence": qualified.boptest_verification_path,
        "verification_artifact_count": len(qualified.verification_artifact_paths),
        "room_temperature_changed": len(set(room_temperatures)) > 1,
        "room_temperatures_kelvin": room_temperatures,
        "oracle_passed": evidence["oracles"][0]["passed"],
        "boptest_version": evidence["runtime"]["version"],
        "boptest_kpis": evidence["runtime"]["kpis"],
        "approved_artifact": str(exported),
        "review_bundle": str(review_bundle),
        "review_bundle_contains_boptest_evidence": True,
        "approval_mode": "self-asserted integration-test identity",
        "boptest_qualified": True,
        "niagara_runtime_qualified": False,
        "live_deployment_allowed": False,
    }

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(retained, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(arguments.output)
    print(
        json.dumps(
            {
                "status": "pass",
                "run_id": approved.id,
                "evidence": str(arguments.output),
                "review_bundle": str(review_bundle),
            }
        )
    )


if __name__ == "__main__":
    main()
