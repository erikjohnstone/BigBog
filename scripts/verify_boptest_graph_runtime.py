from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from bactalk.api import create_app
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
    SequenceSpec,
)
from bactalk.integrations.boptest_graph import (
    BoptestActuatorBinding,
    BoptestGraphMap,
    BoptestMeasurementBinding,
    BoptestTrajectoryOracle,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _require(response: object, status_code: int, label: str) -> None:
    actual = getattr(response, "status_code", None)
    if actual != status_code:
        text = getattr(response, "text", "")
        raise RuntimeError(f"{label} returned {actual}, expected {status_code}: {text}")


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
    parser.add_argument("--time-period")
    parser.add_argument(
        "--electricity-price",
        choices=["constant", "dynamic", "highly_dynamic"],
    )
    parser.add_argument(
        "--temperature-uncertainty",
        choices=["none", "low", "medium", "high"],
    )
    parser.add_argument(
        "--solar-uncertainty",
        choices=["none", "low", "medium", "high"],
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--suite",
        action="store_true",
        help="Qualify peak cooling and peak heating as one digest-bound matrix",
    )
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
    queue_url = os.getenv(
        "BACTALK_QUEUE_URL",
        "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0",
    )
    queue_name = f"bactalk-boptest-qualification-smoke-{uuid4().hex}"
    os.environ["BACTALK_QUALIFICATION_QUEUE"] = queue_name
    os.environ["BACTALK_BOPTEST_URL"] = arguments.base_url
    jobs_root = arguments.run_root.parent / "qualification-jobs"
    client = TestClient(create_app(arguments.run_root))
    catalog_response = client.get("/api/integrations/boptest/catalog")
    _require(catalog_response, 200, "BOPTEST test-case catalog")
    catalog = catalog_response.json()
    if mapping.test_case not in catalog["test_cases"]:
        raise RuntimeError(
            f"configured test case {mapping.test_case!r} is not advertised by BOPTEST"
        )
    contract_response = client.get(
        f"/api/integrations/boptest/catalog/{mapping.test_case}"
    )
    _require(contract_response, 200, "BOPTEST test-case contract inspection")
    test_case_contract = contract_response.json()
    measurement_names = {item["name"] for item in test_case_contract["measurements"]}
    input_names = {item["name"] for item in test_case_contract["inputs"]}
    required_measurements = {item.measurement for item in mapping.measurements}
    required_inputs = {
        name
        for item in mapping.actuators
        for name in (item.actuator, item.activation_actuator)
        if name is not None
    }
    if not required_measurements <= measurement_names or not required_inputs <= input_names:
        raise RuntimeError("configured mapping is absent from the inspected BOPTEST contract")
    if not test_case_contract["clean_stop"] or test_case_contract["initialized"]:
        raise RuntimeError("BOPTEST catalog inspection crossed its read-only lifecycle boundary")
    created = client.post("/api/runs", json=contractor_job().model_dump(mode="json"))
    _require(created, 201, "candidate creation")
    run_id = created.json()["id"]

    denied = client.get(f"/api/runs/{run_id}/export")
    _require(denied, 403, "pre-approval export")
    scenario = {
        key: value
        for key, value in {
            "time_period": arguments.time_period,
            "electricity_price": arguments.electricity_price,
            "temperature_uncertainty": arguments.temperature_uncertainty,
            "solar_uncertainty": arguments.solar_uncertainty,
            "seed": arguments.seed,
        }.items()
        if value is not None
    }
    if arguments.suite:
        if scenario:
            raise SystemExit("--suite defines its own scenarios; do not combine scenario flags")
        suite_scenarios = [
            {
                "time_period": "peak_cool_day",
                "electricity_price": "dynamic",
                "temperature_uncertainty": "medium",
                "solar_uncertainty": "low",
                "seed": 42,
            },
            {
                "time_period": "peak_heat_day",
                "electricity_price": "constant",
            },
        ]
        qualification = {
            "mapping": mapping.model_dump(mode="json"),
            "cases": [
                {
                    "id": case_id,
                    "oracles": [oracle.model_dump(mode="json")],
                    "steps": arguments.steps,
                    "step_seconds": arguments.step,
                    "start_time": 0.0,
                    "warmup_period": 0.0,
                    "scenario": case_scenario,
                }
                for case_id, case_scenario in zip(
                    ("peak-cooling", "peak-heating"), suite_scenarios, strict=True
                )
            ],
        }
    else:
        suite_scenarios = []
        qualification = {
            "mapping": mapping.model_dump(mode="json"),
            "oracles": [oracle.model_dump(mode="json")],
            "steps": arguments.steps,
            "step_seconds": arguments.step,
            "start_time": 0.0,
            "warmup_period": 0.0,
        }
        if scenario:
            qualification["scenario"] = scenario
    queued = client.post(
        f"/api/runs/{run_id}/qualification-jobs/boptest",
        json=qualification,
    )
    _require(queued, 202, "BOPTEST qualification queue submission")
    job_id = queued.json()["id"]
    worker_environment = {
        **os.environ,
        "BACTALK_QUEUE_URL": queue_url,
        "BACTALK_QUALIFICATION_QUEUE": queue_name,
        "BACTALK_BOPTEST_URL": arguments.base_url,
        "PYTHONPATH": str(ROOT / "src"),
    }
    worker = subprocess.run(
        [
            sys.executable,
            "-m",
            "bactalk.cli",
            "qualification-worker",
            "--burst",
            "--queue",
            queue_name,
            "--output",
            str(arguments.run_root),
            "--jobs",
            str(jobs_root),
        ],
        cwd=ROOT,
        env=worker_environment,
        capture_output=True,
        text=True,
        timeout=1_800,
    )
    if worker.returncode != 0:
        raise RuntimeError(
            "qualification worker failed: "
            f"stdout={worker.stdout[-4_000:]}, stderr={worker.stderr[-4_000:]}"
        )
    job = client.get(f"/api/qualification-jobs/{job_id}")
    _require(job, 200, "retained qualification job")
    if job.json()["status"] != "succeeded":
        raise RuntimeError(f"qualification job did not succeed: {job.json()}")

    retained = client.get(f"/api/runs/{run_id}/verify/boptest")
    _require(retained, 200, "retained BOPTEST evidence")
    evidence = retained.json()
    qualified = client.get(f"/api/runs/{run_id}")
    _require(qualified, 200, "qualified candidate")
    if qualified.json()["status"] != "ready_for_review":
        raise SystemExit("BOPTEST trajectory oracle failed")
    runtime_cases = (
        evidence["cases"]
        if arguments.suite
        else [
            {
                "id": "single-run",
                "runtime": evidence["runtime"],
                "oracles": evidence["oracles"],
            }
        ]
    )
    requested_scenarios = suite_scenarios if arguments.suite else ([scenario] if scenario else [])
    room_temperatures_by_case: dict[str, list[float]] = {}
    scenario_states: list[dict[str, object]] = []
    for index, case in enumerate(runtime_cases):
        trajectory = case["runtime"]["trajectory"]
        temperatures = [
            float(row["measurements"]["zon_reaTRooAir_y"]) for row in trajectory
        ]
        room_temperatures_by_case[case["id"]] = temperatures
        if len(set(temperatures)) <= 1:
            raise SystemExit(
                f"BOPTEST room temperature did not respond in case {case['id']}"
            )
        if index < len(requested_scenarios):
            scenario_state = case["runtime"].get("scenario_state")
            if not isinstance(scenario_state, dict):
                raise SystemExit(
                    f"BOPTEST case {case['id']} omitted requested scenario readback"
                )
            for key, value in requested_scenarios[index].items():
                expected = (
                    None
                    if key in {"temperature_uncertainty", "solar_uncertainty"}
                    and value == "none"
                    else value
                )
                if scenario_state.get(key) != expected:
                    raise SystemExit(
                        f"BOPTEST scenario readback mismatch in {case['id']} for {key}: "
                        f"expected {expected!r}, got {scenario_state.get(key)!r}"
                    )
            scenario_states.append(scenario_state)
    room_temperatures = [
        value for values in room_temperatures_by_case.values() for value in values
    ]
    all_oracles_passed = all(
        oracle_result["passed"]
        for case in runtime_cases
        for oracle_result in case["oracles"]
    )

    approved = client.post(
        f"/api/runs/{run_id}/approve",
        json={"reviewer": "BACTalk Integration Test Reviewer"},
    )
    _require(approved, 200, "candidate approval")
    exported = client.get(f"/api/runs/{run_id}/export")
    _require(exported, 200, "approved artifact export")
    review_bundle = client.get(f"/api/runs/{run_id}/review-bundle")
    _require(review_bundle, 200, "approved review bundle export")
    with zipfile.ZipFile(io.BytesIO(review_bundle.content)) as archive:
        bundle_entries = archive.namelist()
    if "boptest-verification/evidence.json" not in bundle_entries:
        raise SystemExit("review bundle omitted signed BOPTEST evidence")

    retained = {
        "schema": "bactalk.boptest-contractor-e2e/v2",
        "status": "pass",
        "run_id": run_id,
        "workflow": [
            "installed_boptest_catalog_discovered",
            "exact_test_case_io_inspected_and_stopped",
            "contractor_job_created",
            "deterministic_acceptance_tests_passed",
            "niagara_bog_generated",
            "preapproval_export_denied",
            "real_boptest_closed_loop_passed",
            *(
                ["multi_scenario_matrix_passed"]
                if arguments.suite
                else []
            ),
            *(
                ["native_boptest_scenario_applied_and_read_back"]
                if requested_scenarios
                else []
            ),
            "pyfunnel_oracle_passed",
            "simulation_evidence_bound_to_artifact_digest",
            "test_identity_approved",
            "approved_bog_and_review_bundle_exported",
        ],
        "candidate_artifact_sha256": created.json()["artifact_sha256"],
        "qualified_artifact_sha256": qualified.json()["artifact_sha256"],
        "qualification_changed_digest": (
            created.json()["artifact_sha256"] != qualified.json()["artifact_sha256"]
        ),
        "preapproval_export_denied": True,
        "boptest_catalog": catalog,
        "inspected_test_case_contract": test_case_contract,
        "qualification_job": job.json(),
        "qualified_run": qualified.json(),
        "runtime_evidence": evidence,
        "qualification_evidence": qualified.json()["boptest_verification_path"],
        "verification_artifact_count": len(qualified.json()["verification_artifact_paths"]),
        "room_temperature_changed": len(set(room_temperatures)) > 1,
        "room_temperatures_kelvin": room_temperatures,
        "room_temperatures_by_case_kelvin": room_temperatures_by_case,
        "scenario_request": scenario or None,
        "scenario_state": scenario_states[0] if len(scenario_states) == 1 else None,
        "scenario_cases": [
            {
                "id": case["id"],
                "request": requested_scenarios[index],
                "state": scenario_states[index],
            }
            for index, case in enumerate(runtime_cases[: len(requested_scenarios)])
        ],
        "scenario_readback_verified": bool(requested_scenarios),
        "scenario_matrix_verified": arguments.suite and len(runtime_cases) == 2,
        "oracle_passed": all_oracles_passed,
        "boptest_version": runtime_cases[0]["runtime"]["version"],
        "boptest_kpis": {
            case["id"]: case["runtime"]["kpis"] for case in runtime_cases
        },
        "approved_run": approved.json(),
        "approved_artifact": {
            "bytes": len(exported.content),
            "sha256": _sha256(exported.content),
        },
        "review_bundle": {
            "bytes": len(review_bundle.content),
            "sha256": _sha256(review_bundle.content),
            "members": sorted(bundle_entries),
        },
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
                "run_id": run_id,
                "evidence": str(arguments.output),
                "job_id": job_id,
            }
        )
    )


if __name__ == "__main__":
    main()
