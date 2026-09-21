from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from bactalk.demo import demo_job
from bactalk.domain import (
    AcceptanceCase,
    DataType,
    JobSpec,
    OutputExpectation,
    canonical_json,
)
from bactalk.integrations.bacnet_lab import (
    LabObjectConfig,
    VirtualBacnetLab,
    build_bacnet_lab_export,
    probe_manifest_with_bac0,
)
from bactalk.integrations.virtual_actuator import VirtualActuatorFault
from bactalk.stack_lock import locked_revision


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_export(root: Path, base_port: int) -> Path:
    export = build_bacnet_lab_export(demo_job(), base_port=base_port)
    assert export is not None
    for artifact in export.artifacts:
        path = root / artifact.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content, encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest_path.write_text(canonical_json(export.manifest), encoding="utf-8")
    return manifest_path


def _actuator_job() -> JobSpec:
    payload = demo_job().model_dump(mode="json")
    payload["points"].extend(
        [
            {
                "name": "DamperPosition",
                "label": "VAV damper position",
                "data_type": "numeric",
                "role": "status",
                "units": "%",
                "default": 0.0,
                "bacnet_device_instance": 120012,
                "bacnet_object": "analog-input,2",
            },
            {
                "name": "DamperOpenProof",
                "label": "VAV damper open proof",
                "data_type": "boolean",
                "role": "status",
                "default": False,
                "bacnet_device_instance": 120012,
                "bacnet_object": "binary-input,1",
            },
            {
                "name": "DamperClosedProof",
                "label": "VAV damper closed proof",
                "data_type": "boolean",
                "role": "status",
                "default": True,
                "bacnet_device_instance": 120012,
                "bacnet_object": "binary-input,2",
            },
        ]
    )
    payload["bacnet_scan"]["devices"][0]["objects"].extend(
        [
            {
                "object_id": "analog-input,2",
                "name": "Damper Position",
                "data_type": "numeric",
                "writable": False,
                "units": "%",
                "present_value": 0.0,
            },
            {
                "object_id": "binary-input,1",
                "name": "Damper Open Proof",
                "data_type": "boolean",
                "writable": False,
                "present_value": False,
            },
            {
                "object_id": "binary-input,2",
                "name": "Damper Closed Proof",
                "data_type": "boolean",
                "writable": False,
                "present_value": True,
            },
        ]
    )
    payload["virtual_actuators"] = [
        {
            "id": "SupplyDamper",
            "kind": "damper",
            "command_point": "DamperCommand",
            "position_point": "DamperPosition",
            "open_proof_point": "DamperOpenProof",
            "closed_proof_point": "DamperClosedProof",
            "stroke_open_seconds": 0.2,
            "stroke_close_seconds": 0.2,
            "proof_timeout_seconds": 0.1,
            "leakage_percent": 1.0,
            "flow_exponent": 1.5,
        }
    ]
    return JobSpec.model_validate(payload)


def test_generated_bacnet_device_is_readable_and_commandable_over_real_udp(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        server_port = _free_udp_port()
        client_port = _free_udp_port()
        manifest_path = _write_export(tmp_path, server_port)
        lab = VirtualBacnetLab.load(manifest_path)
        await lab.start()

        from bacpypes3.app import Application

        client = Application.from_args(
            SimpleNamespace(
                vendoridentifier=999,
                instance=4_194_000,
                name="BACTalk-Proof-Client",
                address=f"127.0.0.1/32:{client_port}",
                foreign=None,
                network=0,
                ttl=30,
                bbmd=None,
            )
        )
        try:
            await asyncio.sleep(0.05)
            address = f"127.0.0.1:{server_port}"
            zone_temp = await asyncio.wait_for(
                client.read_property(address, "analog-input,1", "present-value"),
                timeout=2,
            )
            assert float(zone_temp) == 76.0

            await asyncio.wait_for(
                client.write_property(
                    address,
                    "analog-output,1",
                    "present-value",
                    61.5,
                    priority=8,
                ),
                timeout=2,
            )
            damper = await asyncio.wait_for(
                client.read_property(address, "analog-output,1", "present-value"),
                timeout=2,
            )
            assert float(damper) == 61.5

            lab.set_present_value("ZoneTemp", 81.25)
            updated = await asyncio.wait_for(
                client.read_property(address, "analog-input,1", "present-value"),
                timeout=2,
            )
            assert float(updated) == 81.25
        finally:
            client.close()
            lab.close()

    asyncio.run(exercise())


def test_bac0_independently_reads_generated_virtual_controller(tmp_path: Path) -> None:
    async def exercise() -> None:
        server_port = _free_udp_port()
        client_port = _free_udp_port()
        manifest_path = _write_export(tmp_path, server_port)
        lab = VirtualBacnetLab.load(manifest_path)
        await lab.start()
        try:
            result = await probe_manifest_with_bac0(
                manifest_path,
                client_port=client_port,
            )
        finally:
            lab.close()

        assert result["passed"] is True
        assert result["writes_performed"] is False
        assert float(result["values"]["ZoneTemp"]) == 76.0
        assert float(result["values"]["DamperCommand"]) == 0.0

    asyncio.run(exercise())


def test_acceptance_runner_drives_inputs_and_captures_controller_output(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        job = demo_job().model_copy(
            update={
                "acceptance_tests": [
                    AcceptanceCase(
                        name="hot zone opens damper",
                        inputs={"ZoneTemp": 81.0},
                        expectations=[
                            OutputExpectation(
                                target="DamperCommand",
                                value=55.0,
                                tolerance=0.01,
                            )
                        ],
                        step_seconds=1.0,
                    )
                ]
            }
        )
        server_port = _free_udp_port()
        export = build_bacnet_lab_export(job, base_port=server_port)
        assert export is not None
        for artifact in export.artifacts:
            path = tmp_path / artifact.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(artifact.content, encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(canonical_json(export.manifest), encoding="utf-8")
        lab = VirtualBacnetLab.load(manifest_path)
        await lab.start()

        from bacpypes3.app import Application

        client = Application.from_args(
            SimpleNamespace(
                vendoridentifier=999,
                instance=4_193_999,
                name="BACTalk-Acceptance-Controller",
                address=f"127.0.0.1/32:{_free_udp_port()}",
                foreign=None,
                network=0,
                ttl=30,
                bbmd=None,
            )
        )

        async def emulate_external_controller() -> None:
            await asyncio.sleep(0.005)
            assert lab.get_present_value("ZoneTemp") == 81.0
            await client.write_property(
                f"127.0.0.1:{server_port}",
                "analog-output,1",
                "present-value",
                55.0,
                priority=8,
            )

        controller = asyncio.create_task(emulate_external_controller())
        try:
            # Leave enough wall-clock time for the real UDP write to traverse the
            # local BACnet stack even when the complete integration suite is busy.
            report = await lab.run_acceptance_scenarios(time_scale=0.05)
            await controller
        finally:
            client.close()
            lab.close()

        assert report.passed is True
        assert report.engine == "bacpypes3-loopback-external-controller"
        assert report.coverage["executed_steps"] == 1
        assert report.scenarios[0].samples == [{"DamperCommand": 55.0}]

    asyncio.run(exercise())


def test_generated_lab_is_loopback_only_and_retains_source_identity(tmp_path: Path) -> None:
    server_port = _free_udp_port()
    manifest_path = _write_export(tmp_path, server_port)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    device = json.loads((tmp_path / manifest["devices"][0]["config"]).read_text())

    assert manifest["mode"] == "isolated-loopback"
    assert manifest["safety"]["live_network_routes_allowed"] is False
    assert device["device_instance"] == 120012
    assert device["source_address"] == "192.0.2.12/24:47808"
    assert device["bind_address"] == f"127.0.0.1/32:{server_port}"
    assert {item["object_identifier"] for item in device["objects"]} == {
        "analog-input,1",
        "analog-output,1",
        "analog-output,2",
    }

    independent = manifest["independent_protocol_oracle"]
    assert independent["license"] == "MIT"
    assert independent["revision"] == locked_revision("bacnet-simulator")
    external_device = json.loads(
        (tmp_path / "independent-simulator/devices/120012.yaml").read_text()
    )
    assert external_device["device_id"] == 120012
    assert {item["object_type"] for item in external_device["points"]} == {
        "analogInput",
        "analogOutput",
    }
    assert (tmp_path / independent["settings"]).is_file()
    assert (tmp_path / independent["launcher"]).is_file()


def test_all_common_analog_binary_and_multistate_objects_construct() -> None:
    async def exercise() -> None:
        object_types = [
            "analog-input",
            "analog-output",
            "analog-value",
            "binary-input",
            "binary-output",
            "binary-value",
            "multi-state-input",
            "multi-state-output",
            "multi-state-value",
        ]
        for object_type in object_types:
            binary = object_type.startswith("binary-")
            multistate = object_type.startswith("multi-state-")
            config = LabObjectConfig(
                object_identifier=f"{object_type},1",
                object_name=object_type,
                source_object_name=object_type,
                data_type=DataType.BOOLEAN if binary else DataType.NUMERIC,
                present_value=False if binary else 1 if multistate else 2.5,
                controller_writable=object_type.endswith(("-output", "-value")),
                scenario_injectable=object_type.endswith("-input"),
                command_capture=not object_type.endswith("-input"),
            )
            obj = VirtualBacnetLab._object(config)
            await asyncio.sleep(0)
            assert obj.objectIdentifier is not None

    asyncio.run(exercise())


def test_real_bacnet_command_drives_virtual_damper_motion_proofs_and_faults(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        server_port = _free_udp_port()
        export = build_bacnet_lab_export(_actuator_job(), base_port=server_port)
        assert export is not None
        for artifact in export.artifacts:
            path = tmp_path / artifact.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(artifact.content, encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(canonical_json(export.manifest), encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["actuator_models"][0]["id"] == "SupplyDamper"

        lab = VirtualBacnetLab.load(manifest_path)
        await lab.start()
        from bacpypes3.app import Application

        client = Application.from_args(
            SimpleNamespace(
                vendoridentifier=999,
                instance=4_193_998,
                name="BACTalk-Actuator-Proof-Client",
                address=f"127.0.0.1/32:{_free_udp_port()}",
                foreign=None,
                network=0,
                ttl=30,
                bbmd=None,
            )
        )
        address = f"127.0.0.1:{server_port}"
        try:
            await client.write_property(
                address,
                "analog-output,1",
                "present-value",
                100.0,
                priority=8,
            )
            await asyncio.sleep(0.3)
            position = await client.read_property(
                address,
                "analog-input,2",
                "present-value",
            )
            open_proof = await client.read_property(
                address,
                "binary-input,1",
                "present-value",
            )
            assert float(position) == pytest.approx(100.0)
            assert str(open_proof) == "active"
            assert lab.actuator_snapshot("SupplyDamper")["flow_percent"] == 100.0

            lab.set_actuator_fault(
                "SupplyDamper",
                VirtualActuatorFault(stuck_position=40.0, open_proof_failed=True),
            )
            await asyncio.sleep(0.12)
            stuck_position = await client.read_property(
                address,
                "analog-input,2",
                "present-value",
            )
            failed_proof = await client.read_property(
                address,
                "binary-input,1",
                "present-value",
            )
            snapshot = lab.actuator_snapshot("SupplyDamper")
            assert float(stuck_position) == pytest.approx(40.0)
            assert str(failed_proof) == "inactive"
            assert snapshot["command_feedback_mismatch"] is True
            assert snapshot["proof_alarm"] is True

            lab.clear_actuator_fault("SupplyDamper")
            await asyncio.sleep(0.2)
            recovered = lab.actuator_snapshot("SupplyDamper")
            assert recovered["physical_position"] == pytest.approx(100.0)
            assert recovered["proof_alarm"] is False
        finally:
            client.close()
            lab.close()

    asyncio.run(exercise())
