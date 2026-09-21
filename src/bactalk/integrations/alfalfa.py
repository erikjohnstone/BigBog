from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


class AlfalfaClientLike(Protocol):
    def submit(self, model_path: str, wait_for_status: bool = True) -> str: ...

    def start(
        self,
        run_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        timescale: int = 5,
        external_clock: bool = False,
        realtime: bool = False,
        wait_for_status: bool = True,
    ) -> None: ...

    def get_inputs(self, run_id: str) -> list[str]: ...

    def set_inputs(self, run_id: str, inputs: dict[str, float]) -> None: ...

    def get_outputs(self, run_id: str) -> dict[str, Any]: ...

    def get_sim_time(self, run_id: str) -> datetime: ...

    def advance(self, run_id: str) -> None: ...

    def stop(self, run_id: str, wait_for_status: bool = True) -> None: ...

    def status(self, run_id: str) -> str: ...


@dataclass(frozen=True)
class AlfalfaRuntimeProfile:
    start: datetime = datetime(2019, 1, 1, 0, 0)
    end: datetime = datetime(2019, 1, 1, 0, 5)
    advances: int = 5
    required_inputs: tuple[str, ...] = (
        "hvac_oveAhu_TSupSet_u",
        "hvac_oveAhu_yCoo_u",
        "hvac_oveAhu_yFan_u",
        "hvac_oveAhu_yHea_u",
        "hvac_oveAhu_yOA_u",
    )
    required_outputs: tuple[str, ...] = (
        "hvac_oveAhu_yFan_y",
        "hvac_reaAhu_TSup_y",
        "hvac_reaZonCor_TZon_y",
    )
    commands: dict[str, float] = field(
        default_factory=lambda: {"hvac_oveAhu_yFan_u": 0.37}
    )
    command_echoes: dict[str, str] = field(
        default_factory=lambda: {"hvac_oveAhu_yFan_u": "hvac_oveAhu_yFan_y"}
    )
    echo_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        if self.advances <= 0:
            raise ValueError("Alfalfa advances must be positive")
        if self.end <= self.start:
            raise ValueError("Alfalfa end time must be after start time")
        if not set(self.commands) <= set(self.required_inputs):
            raise ValueError("Every Alfalfa command must also be a required input")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_time(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _changed_outputs(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(name for name in before.keys() & after.keys() if before[name] != after[name])


def qualify_alfalfa_runtime(
    client: AlfalfaClientLike,
    model_path: Path,
    *,
    profile: AlfalfaRuntimeProfile | None = None,
    server_version: Any = None,
    client_version: str | None = None,
    images: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Exercise one real external-clock Alfalfa lifecycle and return retained evidence.

    This qualifier intentionally never talks BACnet or Niagara. It proves only the
    Alfalfa model-service boundary and names every broader claim it does not prove.
    """

    profile = profile or AlfalfaRuntimeProfile()
    model_path = model_path.resolve()
    evidence: dict[str, Any] = {
        "schema": "bactalk.alfalfa-runtime-evidence/v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "scope": "isolated Alfalfa whole-building FMU runtime qualification",
        "status": "fail",
        "profile": {
            "start": profile.start.isoformat(),
            "end": profile.end.isoformat(),
            "advances": profile.advances,
            "required_inputs": list(profile.required_inputs),
            "required_outputs": list(profile.required_outputs),
            "commands": profile.commands,
            "command_echoes": profile.command_echoes,
            "echo_tolerance": profile.echo_tolerance,
        },
        "runtime": {
            "server_version": server_version,
            "client_version": client_version,
            "images": images or {},
            "model_name": model_path.name,
            "model_sha256": _sha256(model_path) if model_path.is_file() else None,
        },
        "results": {},
        "errors": [],
        "not_proven": [
            "Niagara import, execution, restart, or readback",
            "BACnet protocol behavior or capacity",
            "controller hardware-in-loop behavior",
            "production Linux capacity or high availability",
            "field-equipment or occupied-building behavior",
            "live-building deployment readiness",
        ],
    }
    run_id: str | None = None
    started = False
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    start_time: datetime | None = None
    end_time: datetime | None = None

    try:
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        run_id = str(client.submit(str(model_path)))
        evidence["runtime"]["run_id"] = run_id
        client.start(
            run_id,
            profile.start,
            profile.end,
            external_clock=True,
        )
        started = True
        evidence["results"]["status_after_start"] = str(client.status(run_id))

        inputs = sorted(client.get_inputs(run_id))
        before = client.get_outputs(run_id)
        missing_inputs = sorted(set(profile.required_inputs) - set(inputs))
        missing_outputs = sorted(set(profile.required_outputs) - set(before))
        evidence["results"].update(
            {
                "input_count": len(inputs),
                "output_count": len(before),
                "input_names": inputs,
                "output_names": sorted(before),
                "missing_inputs": missing_inputs,
                "missing_outputs": missing_outputs,
            }
        )
        if missing_inputs or missing_outputs:
            raise RuntimeError(
                f"Alfalfa signal contract is incomplete: "
                f"missing inputs={missing_inputs}, missing outputs={missing_outputs}"
            )

        start_time = client.get_sim_time(run_id)
        client.set_inputs(run_id, dict(profile.commands))
        snapshots: list[dict[str, Any]] = []
        for index in range(profile.advances):
            client.advance(run_id)
            current_time = client.get_sim_time(run_id)
            current_outputs = client.get_outputs(run_id)
            snapshots.append(
                {
                    "advance": index + 1,
                    "simulation_time": _render_time(current_time),
                    "observed": {
                        name: current_outputs.get(name) for name in profile.required_outputs
                    },
                }
            )
        end_time = client.get_sim_time(run_id)
        after = client.get_outputs(run_id)
        changed = _changed_outputs(before, after)
        evidence["results"].update(
            {
                "advances_completed": len(snapshots),
                "start_simulation_time": _render_time(start_time),
                "end_simulation_time": _render_time(end_time),
                "simulated_seconds": (end_time - start_time).total_seconds(),
                "changed_output_count": len(changed),
                "changed_outputs": changed,
                "snapshots": snapshots,
            }
        )

        if len(snapshots) != profile.advances:
            raise RuntimeError("Alfalfa did not complete every requested advance")
        if end_time <= start_time:
            raise RuntimeError("Alfalfa simulation time did not advance")
        if not changed:
            raise RuntimeError("Alfalfa exposed no changing output across the trajectory")

        echoes: dict[str, Any] = {}
        for command_name, output_name in profile.command_echoes.items():
            command_value = profile.commands[command_name]
            output_value = after.get(output_name)
            matched = (
                isinstance(output_value, (int, float))
                and abs(float(output_value) - command_value) <= profile.echo_tolerance
            )
            echoes[command_name] = {
                "output": output_name,
                "command_value": command_value,
                "output_value": output_value,
                "matched": matched,
            }
            if not matched:
                raise RuntimeError(
                    f"Alfalfa command echo mismatch for {command_name}: {output_value!r}"
                )
        evidence["results"]["command_echoes"] = echoes
    except Exception as exc:  # retained evidence must include service/client failures
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if run_id is not None and started:
            try:
                client.stop(run_id)
                stopped_status = str(client.status(run_id))
                evidence["results"]["status_after_stop"] = stopped_status
                evidence["results"]["clean_stop"] = stopped_status.upper() == "COMPLETE"
                if not evidence["results"]["clean_stop"]:
                    evidence["errors"].append(
                        f"Alfalfa stopped in unexpected status {stopped_status!r}"
                    )
            except Exception as exc:  # preserve the primary failure and cleanup failure
                evidence["results"]["clean_stop"] = False
                evidence["errors"].append(f"stop {type(exc).__name__}: {exc}")

    if not evidence["errors"] and evidence["results"].get("clean_stop") is True:
        evidence["status"] = "pass"
    return evidence


def write_evidence_atomic(path: Path, evidence: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
