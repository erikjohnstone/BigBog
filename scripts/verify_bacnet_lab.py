from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace

from bactalk.demo import demo_job
from bactalk.domain import AcceptanceCase, OutputExpectation, canonical_json
from bactalk.integrations.bacnet_lab import (
    VirtualBacnetLab,
    build_bacnet_lab_export,
    probe_manifest_with_bac0,
)


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def verify() -> dict[str, object]:
    server_port = _free_udp_port()
    client_port = _free_udp_port()
    with tempfile.TemporaryDirectory(prefix="bactalk-bacnet-lab-") as temporary:
        root = Path(temporary)
        job = demo_job().model_copy(
            update={
                "acceptance_tests": [
                    AcceptanceCase(
                        name="external controller command capture",
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
        export = build_bacnet_lab_export(job, base_port=server_port)
        if export is None:
            raise RuntimeError("demo job did not generate a BACnet lab")
        for artifact in export.artifacts:
            path = root / artifact.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(artifact.content, encoding="utf-8")
        manifest_path = root / "manifest.json"
        manifest_path.write_text(canonical_json(export.manifest), encoding="utf-8")

        lab = VirtualBacnetLab.load(manifest_path)
        await lab.start()
        try:
            result = await probe_manifest_with_bac0(
                manifest_path,
                client_port=client_port,
            )
            lab.set_present_value("ZoneTemp", 81.0)
            injected_value = lab.get_present_value("ZoneTemp")

            from bacpypes3.app import Application

            controller_client = Application.from_args(
                SimpleNamespace(
                    vendoridentifier=999,
                    instance=4_193_998,
                    name="BACTalk-Contract-Controller",
                    address=f"127.0.0.1/32:{_free_udp_port()}",
                    foreign=None,
                    network=0,
                    ttl=30,
                    bbmd=None,
                )
            )

            async def emulate_external_controller() -> None:
                await asyncio.sleep(0.005)
                await controller_client.write_property(
                    f"127.0.0.1:{server_port}",
                    "analog-output,1",
                    "present-value",
                    55.0,
                    priority=8,
                )

            try:
                controller = asyncio.create_task(emulate_external_controller())
                acceptance = await lab.run_acceptance_scenarios(time_scale=0.01)
                await controller
            finally:
                controller_client.close()
        finally:
            lab.close()

        if not result["passed"] or float(result["values"]["ZoneTemp"]) != 76.0:
            raise RuntimeError("BAC0 did not read the generated virtual controller correctly")
        if injected_value != 81.0:
            raise RuntimeError("scenario injection did not update the virtual controller")
        if not acceptance.passed:
            raise RuntimeError("BACnet acceptance runner did not capture controller output")
        return {
            "passed": True,
            "mode": export.manifest["mode"],
            "devices": len(export.manifest["devices"]),
            "objects": sum(item["object_count"] for item in export.manifest["devices"]),
            "bac0_points_read": result["point_count"],
            "scenario_injection_verified": True,
            "acceptance_result_capture_verified": True,
            "acceptance_engine": acceptance.engine,
            "live_network_routes_allowed": export.manifest["safety"][
                "live_network_routes_allowed"
            ],
            "mstp_boundary": "identity mirrored over BACnet/IP; serial/HIL not claimed",
        }


def main() -> int:
    print(json.dumps(asyncio.run(verify()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
