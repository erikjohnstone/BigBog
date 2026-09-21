from __future__ import annotations

import asyncio
import hashlib
import math
import platform
import resource
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bactalk.domain import canonical_json
from bactalk.integrations.bacnet_lab import BacnetLabManifest, VirtualBacnetLab
from bactalk.optional_dependencies import BACPYPES3


@dataclass(frozen=True, slots=True)
class BacnetScaleProfile:
    devices: int = 100
    analog_inputs_per_device: int = 16
    binary_inputs_per_device: int = 2
    analog_outputs_per_device: int = 1
    binary_outputs_per_device: int = 1
    poll_rounds: int = 2
    cov_subscriptions: int | None = None
    cov_burst_rounds: int = 2
    concurrency: int = 50
    base_port: int = 40_000
    request_timeout_seconds: float = 3.0
    outage_timeout_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not 1 <= self.devices <= 10_000:
            raise ValueError("devices must be from 1 through 10000")
        counts = (
            self.analog_inputs_per_device,
            self.binary_inputs_per_device,
            self.analog_outputs_per_device,
            self.binary_outputs_per_device,
        )
        if any(count < 0 for count in counts) or sum(counts) < 1:
            raise ValueError("point counts must be non-negative with at least one point per device")
        if sum(counts) > 50_000:
            raise ValueError("points per device cannot exceed 50000")
        if self.analog_outputs_per_device < 1:
            raise ValueError("at least one analog output is required for write qualification")
        if not 1 <= self.poll_rounds <= 100_000:
            raise ValueError("poll_rounds must be from 1 through 100000")
        if self.cov_subscriptions is not None and not 0 <= self.cov_subscriptions <= self.devices:
            raise ValueError("cov_subscriptions must be from 0 through devices")
        if not 1 <= self.cov_burst_rounds <= 10_000:
            raise ValueError("cov_burst_rounds must be from 1 through 10000")
        if self.cov_subscription_count and self.analog_inputs_per_device < 1:
            raise ValueError("COV qualification requires at least one analog input per device")
        if not 1 <= self.concurrency <= 10_000:
            raise ValueError("concurrency must be from 1 through 10000")
        if self.base_port < 1024 or self.base_port + self.devices > 65_534:
            raise ValueError("BACnet device and client port range is invalid")
        for label, value in (
            ("request_timeout_seconds", self.request_timeout_seconds),
            ("outage_timeout_seconds", self.outage_timeout_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be positive and finite")

    @property
    def points_per_device(self) -> int:
        return (
            self.analog_inputs_per_device
            + self.binary_inputs_per_device
            + self.analog_outputs_per_device
            + self.binary_outputs_per_device
        )

    @property
    def total_points(self) -> int:
        return self.devices * self.points_per_device

    @property
    def cov_subscription_count(self) -> int:
        if self.cov_subscriptions is None:
            return min(self.devices, 100)
        return self.cov_subscriptions


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil(percentile * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def _latency_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "samples": len(values),
        "p50_seconds": _percentile(values, 0.50),
        "p95_seconds": _percentile(values, 0.95),
        "p99_seconds": _percentile(values, 0.99),
        "max_seconds": max(values) if values else None,
    }


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _campus_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _object_configs(profile: BacnetScaleProfile, device_index: int) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    groups = (
        ("analog-input", profile.analog_inputs_per_device, "numeric", False, 70.0),
        ("binary-input", profile.binary_inputs_per_device, "boolean", False, False),
        ("analog-output", profile.analog_outputs_per_device, "numeric", True, 0.0),
        ("binary-output", profile.binary_outputs_per_device, "boolean", True, False),
    )
    for object_type, count, data_type, writable, initial in groups:
        for instance in range(1, count + 1):
            name = f"D{device_index:05d}_{object_type}_{instance}"
            configs.append(
                {
                    "object_identifier": f"{object_type},{instance}",
                    "object_name": name,
                    "source_object_name": name,
                    "point_name": None,
                    "data_type": data_type,
                    "present_value": initial,
                    "units": "degreesFahrenheit" if object_type == "analog-input" else None,
                    "controller_writable": writable,
                    "scenario_injectable": object_type.endswith("-input"),
                    "command_capture": writable,
                    "number_of_states": None,
                }
            )
    return configs


def build_synthetic_bacnet_campus(root: Path, profile: BacnetScaleProfile) -> Path:
    """Write a loopback-only campus manifest for repeatable protocol qualification."""

    root.mkdir(parents=True, exist_ok=True)
    devices_dir = root / "devices"
    devices_dir.mkdir(parents=True, exist_ok=True)
    devices: list[dict[str, Any]] = []
    for index in range(profile.devices):
        device_instance = 2_000_000 + index
        port = profile.base_port + index
        relative_path = f"devices/{device_instance}.json"
        config = {
            "device_instance": device_instance,
            "device_name": f"BACTalk-Scale-{index + 1:05d}",
            "vendor_id": 999,
            "source_address": f"synthetic://device/{device_instance}",
            "source_transport": "bacnet_ip",
            "source_network_number": None,
            "source_mac_address": None,
            "bind_address": f"127.0.0.1/32:{port}",
            "network_address": f"127.0.0.1:{port}",
            "objects": _object_configs(profile, index + 1),
        }
        (root / relative_path).write_text(canonical_json(config), encoding="utf-8")
        devices.append(
            {
                "device_instance": device_instance,
                "device_name": config["device_name"],
                "network_address": config["network_address"],
                "config": relative_path,
                "object_count": profile.points_per_device,
            }
        )
    (root / "acceptance-scenarios.json").write_text(
        canonical_json({"format": "bactalk.bacnet-lab-scenarios.v1", "cases": []}),
        encoding="utf-8",
    )
    manifest = {
        "format": "bactalk.bacnet-lab.v1",
        "mode": "isolated-loopback",
        "source": "BACTalk generated scale profile",
        "devices": devices,
        "point_index": {},
        "actuator_models": [],
        "scenario_file": "acceptance-scenarios.json",
        "safety": {
            "bind_scope": "127.0.0.1/32",
            "live_network_routes_allowed": False,
            "writes_affect_virtual_objects_only": True,
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    return manifest_path


class BacnetScaleRunner:
    """Measure a real BACpypes3 UDP campus without contacting an OT network."""

    def __init__(self, profile: BacnetScaleProfile, root: Path):
        self.profile = profile
        self.root = root.resolve()

    async def _bounded_map(self, operation: Any, items: list[Any]) -> list[Any]:
        semaphore = asyncio.Semaphore(self.profile.concurrency)

        async def bounded(item: Any) -> Any:
            async with semaphore:
                return await operation(item)

        return await asyncio.gather(*(bounded(item) for item in items))

    async def run(self) -> dict[str, Any]:
        BACPYPES3.require()
        from bacpypes3.app import Application
        from bacpypes3.pdu import Address

        started = time.perf_counter()
        cpu_started = time.process_time()
        rss_started = _max_rss_bytes()
        manifest_path = build_synthetic_bacnet_campus(self.root, self.profile)
        manifest_bytes = manifest_path.read_bytes()
        manifest = BacnetLabManifest.model_validate_json(manifest_bytes)
        lab = VirtualBacnetLab.load(manifest_path)
        errors: list[dict[str, Any]] = []
        discovery_latencies: list[float] = []
        read_latencies: list[float] = []
        write_latencies: list[float] = []
        cov_setup_latencies: list[float] = []
        cov_notification_latencies: list[float] = []
        discovered = 0
        read_requests = 0
        properties_read = 0
        writes_verified = 0
        cov_subscriptions_verified = 0
        cov_notifications_verified = 0
        outage_detected = False
        recovery_verified = False
        devices_started = 0
        startup_seconds: float | None = None
        client: Any = None

        def failure(stage: str, device: int | None, exc: BaseException | str) -> None:
            message = str(exc) if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
            errors.append({"stage": stage, "device_instance": device, "error": message})

        try:
            startup_started = time.perf_counter()
            await lab.start()
            startup_seconds = time.perf_counter() - startup_started
            devices_started = len(lab.device_apps)
            client = Application.from_args(
                SimpleNamespace(
                    vendoridentifier=999,
                    instance=4_193_900,
                    name="BACTalk-Scale-Client",
                    address=f"127.0.0.1/32:{self.profile.base_port + self.profile.devices}",
                    foreign=None,
                    network=0,
                    ttl=30,
                    bbmd=None,
                )
            )
            await asyncio.sleep(0.05)

            async def discover(summary: dict[str, Any]) -> bool:
                device_instance = int(summary["device_instance"])
                request_started = time.perf_counter()
                try:
                    responses = await asyncio.wait_for(
                        client.who_is(
                            low_limit=device_instance,
                            high_limit=device_instance,
                            address=Address(str(summary["network_address"])),
                            timeout=max(1, math.ceil(self.profile.request_timeout_seconds)),
                        ),
                        timeout=self.profile.request_timeout_seconds + 1.0,
                    )
                    identifiers = {
                        int(response.iAmDeviceIdentifier[1])
                        for response in responses
                        if getattr(response, "iAmDeviceIdentifier", None) is not None
                    }
                    if device_instance not in identifiers:
                        raise ValueError(f"I-Am omitted device {device_instance}")
                    return True
                except Exception as exc:
                    failure("targeted_discovery", device_instance, exc)
                    return False
                finally:
                    discovery_latencies.append(time.perf_counter() - request_started)

            discovery_results = await self._bounded_map(discover, manifest.devices)
            discovered = sum(bool(result) for result in discovery_results)

            object_ids = [
                f"analog-input,{index}"
                for index in range(1, self.profile.analog_inputs_per_device + 1)
            ] + [
                f"binary-input,{index}"
                for index in range(1, self.profile.binary_inputs_per_device + 1)
            ] + [
                f"analog-output,{index}"
                for index in range(1, self.profile.analog_outputs_per_device + 1)
            ] + [
                f"binary-output,{index}"
                for index in range(1, self.profile.binary_outputs_per_device + 1)
            ]
            # BACpypes3 accepts the CLI-style flattened sequence despite its tuple-list
            # annotation: object id, property list, object id, property list, ...
            rpm_parameters: list[Any] = []
            for object_id in object_ids:
                rpm_parameters.extend((object_id, ["presentValue"]))
            read_items = [
                (round_index, summary)
                for round_index in range(1, self.profile.poll_rounds + 1)
                for summary in manifest.devices
            ]

            async def read_device(item: tuple[int, dict[str, Any]]) -> int:
                round_index, summary = item
                device_instance = int(summary["device_instance"])
                request_started = time.perf_counter()
                try:
                    values = await asyncio.wait_for(
                        client.read_property_multiple(
                            Address(str(summary["network_address"])),
                            rpm_parameters,
                        ),
                        timeout=self.profile.request_timeout_seconds,
                    )
                    if len(values) != self.profile.points_per_device:
                        raise ValueError(
                            f"RPM returned {len(values)} values; "
                            f"expected {self.profile.points_per_device}"
                        )
                    return len(values)
                except Exception as exc:
                    failure(f"poll_round_{round_index}", device_instance, exc)
                    return 0
                finally:
                    read_latencies.append(time.perf_counter() - request_started)

            read_results = await self._bounded_map(read_device, read_items)
            read_requests = sum(result > 0 for result in read_results)
            properties_read = sum(read_results)

            async def write_device(summary: dict[str, Any]) -> bool:
                device_instance = int(summary["device_instance"])
                address = str(summary["network_address"])
                expected = float((device_instance % 80) + 10)
                request_started = time.perf_counter()
                try:
                    await asyncio.wait_for(
                        client.write_property(
                            address,
                            "analog-output,1",
                            "present-value",
                            expected,
                            priority=8,
                        ),
                        timeout=self.profile.request_timeout_seconds,
                    )
                    observed = await asyncio.wait_for(
                        client.read_property(address, "analog-output,1", "present-value"),
                        timeout=self.profile.request_timeout_seconds,
                    )
                    if not math.isclose(float(observed), expected, abs_tol=1e-6):
                        raise ValueError(f"write readback was {observed}; expected {expected}")
                    return True
                except Exception as exc:
                    failure("priority_write_readback", device_instance, exc)
                    return False
                finally:
                    write_latencies.append(time.perf_counter() - request_started)

            write_results = await self._bounded_map(write_device, manifest.devices)
            writes_verified = sum(bool(result) for result in write_results)

            cov_contexts: list[tuple[int, Any]] = []
            cov_summaries = manifest.devices[: self.profile.cov_subscription_count]

            async def subscribe_cov(summary: dict[str, Any]) -> tuple[int, Any] | None:
                from bacpypes3.primitivedata import ObjectIdentifier

                device_instance = int(summary["device_instance"])
                request_started = time.perf_counter()
                context = client.change_of_value(
                    Address(str(summary["network_address"])),
                    ObjectIdentifier("analogInput,1"),
                    lifetime=60,
                )
                try:
                    subscription = await asyncio.wait_for(
                        context.__aenter__(),
                        timeout=self.profile.request_timeout_seconds,
                    )
                    return device_instance, subscription
                except Exception as exc:
                    failure("cov_subscribe", device_instance, exc)
                    return None
                finally:
                    cov_setup_latencies.append(time.perf_counter() - request_started)

            async def next_cov_value(
                item: tuple[int, Any],
                *,
                stage: str,
                expected: float,
            ) -> bool:
                device_instance, subscription = item
                request_started = time.perf_counter()

                async def consume() -> Any:
                    while True:
                        prop, value = await subscription.get_value()
                        if str(prop) == "present-value":
                            return value

                try:
                    observed = await asyncio.wait_for(
                        consume(),
                        timeout=self.profile.request_timeout_seconds,
                    )
                    if not math.isclose(float(observed), expected, abs_tol=1e-6):
                        raise ValueError(f"COV value was {observed}; expected {expected}")
                    return True
                except Exception as exc:
                    failure(stage, device_instance, exc)
                    return False
                finally:
                    cov_notification_latencies.append(time.perf_counter() - request_started)

            if cov_summaries:
                entered = await self._bounded_map(subscribe_cov, cov_summaries)
                cov_contexts = [item for item in entered if item is not None]
                initial_results = await self._bounded_map(
                    lambda item: next_cov_value(item, stage="cov_initial", expected=70.0),
                    cov_contexts,
                )
                cov_subscriptions_verified = sum(bool(result) for result in initial_results)
                try:
                    for round_index in range(1, self.profile.cov_burst_rounds + 1):
                        expected = 70.0 + round_index
                        for device_instance, _subscription in cov_contexts:
                            lab.set_object_present_value(
                                device_instance,
                                "analog-input,1",
                                expected,
                            )
                        notification_results = await self._bounded_map(
                            lambda item, current_round=round_index, current_expected=expected: (
                                next_cov_value(
                                    item,
                                    stage=f"cov_burst_{current_round}",
                                    expected=current_expected,
                                )
                            ),
                            cov_contexts,
                        )
                        cov_notifications_verified += sum(
                            bool(result) for result in notification_results
                        )
                finally:
                    async def unsubscribe(item: tuple[int, Any]) -> None:
                        device_instance, subscription = item
                        try:
                            await asyncio.wait_for(
                                subscription.__aexit__(None, None, None),
                                timeout=self.profile.request_timeout_seconds,
                            )
                        except Exception as exc:
                            failure("cov_unsubscribe", device_instance, exc)

                    await self._bounded_map(unsubscribe, cov_contexts)

            fault_device = int(manifest.devices[0]["device_instance"])
            fault_address = str(manifest.devices[0]["network_address"])
            lab.stop_device(fault_device)
            await asyncio.sleep(0.05)
            try:
                await asyncio.wait_for(
                    client.read_property(fault_address, "analog-input,1", "present-value"),
                    timeout=self.profile.outage_timeout_seconds,
                )
                failure("offline_detection", fault_device, "offline device unexpectedly responded")
            except TimeoutError:
                outage_detected = True
            except Exception as exc:
                failure("offline_detection", fault_device, exc)
            await lab.start_device(fault_device)
            await asyncio.sleep(0.05)
            try:
                recovered = await asyncio.wait_for(
                    client.read_property(fault_address, "analog-input,1", "present-value"),
                    timeout=self.profile.request_timeout_seconds,
                )
                recovery_verified = math.isclose(float(recovered), 70.0, abs_tol=1e-6)
                if not recovery_verified:
                    failure("recovery", fault_device, f"unexpected recovered value: {recovered}")
            except Exception as exc:
                failure("recovery", fault_device, exc)
        except Exception as exc:
            failure("runner", None, exc)
        finally:
            if client is not None:
                client.close()
            lab.close()

        wall_seconds = time.perf_counter() - started
        cpu_seconds = time.process_time() - cpu_started
        expected_reads = self.profile.devices * self.profile.poll_rounds
        expected_cov_notifications = (
            self.profile.cov_subscription_count * self.profile.cov_burst_rounds
        )
        passed = (
            not errors
            and discovered == self.profile.devices
            and read_requests == expected_reads
            and properties_read == expected_reads * self.profile.points_per_device
            and writes_verified == self.profile.devices
            and cov_subscriptions_verified == self.profile.cov_subscription_count
            and cov_notifications_verified == expected_cov_notifications
            and outage_detected
            and recovery_verified
        )
        try:
            bacpypes_version = metadata.version("bacpypes3")
        except metadata.PackageNotFoundError:  # pragma: no cover
            bacpypes_version = None
        return {
            "schema": "bactalk.bacnet-scale-evidence/v1",
            "created_at": datetime.now(UTC).isoformat(),
            "status": "pass" if passed else "fail",
            "scope": "isolated BACnet/IP protocol-scale qualification",
            "claims": [
                "real loopback UDP BACnet/IP applications",
                "targeted Who-Is/I-Am identity verification",
                "ReadPropertyMultiple polling",
                "priority-8 writes with present-value readback",
                "confirmed COV subscriptions and burst notifications",
                "single-device outage detection and restart recovery",
            ],
            "not_proven": [
                "broadcast discovery across routed BACnet networks",
                "BBMD, foreign-device, or BACnet/SC behavior",
                "COV load beyond the configured subscription/burst profile",
                "alarm or history throughput",
                "MS/TP token, baud, router, or electrical behavior",
                "licensed Niagara runtime capacity",
                "physical controller or field-equipment capacity",
                "live-building deployment readiness",
            ],
            "profile": {
                "devices": self.profile.devices,
                "points_per_device": self.profile.points_per_device,
                "total_points": self.profile.total_points,
                "poll_rounds": self.profile.poll_rounds,
                "cov_subscriptions": self.profile.cov_subscription_count,
                "cov_burst_rounds": self.profile.cov_burst_rounds,
                "concurrency": self.profile.concurrency,
                "base_port": self.profile.base_port,
                "request_timeout_seconds": self.profile.request_timeout_seconds,
                "outage_timeout_seconds": self.profile.outage_timeout_seconds,
            },
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "bacpypes3": bacpypes_version,
                "artifact_root": str(self.root),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "campus_artifact_sha256": _campus_digest(self.root),
                "startup_seconds": startup_seconds,
                "wall_seconds": wall_seconds,
                "cpu_seconds": cpu_seconds,
                "cpu_to_wall_ratio": cpu_seconds / wall_seconds,
                "max_rss_before_bytes": rss_started,
                "max_rss_after_bytes": _max_rss_bytes(),
            },
            "results": {
                "devices_started": devices_started,
                "devices_discovered": discovered,
                "read_requests_expected": expected_reads,
                "read_requests_passed": read_requests,
                "properties_read": properties_read,
                "writes_expected": self.profile.devices,
                "writes_verified": writes_verified,
                "cov_subscriptions_expected": self.profile.cov_subscription_count,
                "cov_subscriptions_verified": cov_subscriptions_verified,
                "cov_notifications_expected": expected_cov_notifications,
                "cov_notifications_verified": cov_notifications_verified,
                "outage_detected": outage_detected,
                "recovery_verified": recovery_verified,
                "request_throughput_per_second": (
                    (discovered + read_requests + writes_verified) / wall_seconds
                ),
                "property_throughput_per_second": properties_read / wall_seconds,
            },
            "latency": {
                "targeted_discovery": _latency_summary(discovery_latencies),
                "read_property_multiple": _latency_summary(read_latencies),
                "priority_write_and_readback": _latency_summary(write_latencies),
                "cov_subscription_setup": _latency_summary(cov_setup_latencies),
                "cov_notification": _latency_summary(cov_notification_latencies),
            },
            "errors": errors,
        }
