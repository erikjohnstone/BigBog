from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import VirtualActuatorSpec


class VirtualActuatorFault(BaseModel):
    """Composable physical and feedback faults for a virtual actuator."""

    model_config = ConfigDict(extra="forbid")

    command_available: bool = True
    stuck_position: float | None = Field(default=None, ge=0.0, le=100.0)
    minimum_travel: float | None = Field(default=None, ge=0.0, le=100.0)
    maximum_travel: float | None = Field(default=None, ge=0.0, le=100.0)
    feedback_bias: float = Field(default=0.0, ge=-100.0, le=100.0)
    feedback_stuck_position: float | None = Field(default=None, ge=0.0, le=100.0)
    open_proof_failed: bool = False
    closed_proof_failed: bool = False

    @model_validator(mode="after")
    def travel_limits_are_coherent(self) -> VirtualActuatorFault:
        if (
            self.minimum_travel is not None
            and self.maximum_travel is not None
            and self.minimum_travel > self.maximum_travel
        ):
            raise ValueError("minimum_travel cannot exceed maximum_travel")
        return self


class VirtualActuatorSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: float
    effective_target: float
    physical_position: float
    feedback_position: float
    flow_percent: float
    open_proof: bool
    closed_proof: bool
    traveling: bool
    command_feedback_mismatch: bool
    mismatch_seconds: float
    proof_alarm: bool
    command_available: bool


class VirtualActuator:
    """Deterministic stroke/feedback model shared by tests and BACnet emulation.

    Position is expressed as percent of configured travel. ``flow_percent`` is a
    deliberately bounded valve/damper characteristic, not a hydraulic sizing
    model; it represents leakage and a configurable equal-percentage-like curve.
    """

    def __init__(self, spec: VirtualActuatorSpec, *, initial_position: float | None = None):
        self.spec = spec
        initial = spec.fail_position if initial_position is None else float(initial_position)
        self.position = self._clamp(initial, spec.minimum_position, spec.maximum_position)
        self.mismatch_seconds = 0.0
        self.elapsed_seconds = 0.0
        self.last_sample: VirtualActuatorSample | None = None

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return min(max(value, minimum), maximum)

    def step(
        self,
        command: float,
        *,
        step_seconds: float,
        fault: VirtualActuatorFault | None = None,
    ) -> VirtualActuatorSample:
        if not math.isfinite(float(command)):
            raise ValueError("virtual actuator command must be finite")
        if not math.isfinite(step_seconds) or step_seconds < 0.0:
            raise ValueError("virtual actuator step_seconds must be finite and non-negative")
        active_fault = fault or VirtualActuatorFault()
        minimum = max(
            self.spec.minimum_position,
            active_fault.minimum_travel
            if active_fault.minimum_travel is not None
            else self.spec.minimum_position,
        )
        maximum = min(
            self.spec.maximum_position,
            active_fault.maximum_travel
            if active_fault.maximum_travel is not None
            else self.spec.maximum_position,
        )
        if minimum > maximum:
            raise ValueError("actuator fault travel limits do not overlap configured travel")

        requested = self._clamp(float(command), 0.0, 100.0)
        target = requested if active_fault.command_available else self.spec.fail_position
        target = self._clamp(target, minimum, maximum)
        current = self._clamp(self.position, minimum, maximum)
        if active_fault.stuck_position is not None:
            current = self._clamp(active_fault.stuck_position, minimum, maximum)
        else:
            delta = target - current
            if abs(delta) > self.spec.command_deadband and step_seconds:
                stroke = (
                    self.spec.stroke_open_seconds if delta > 0.0 else self.spec.stroke_close_seconds
                )
                maximum_change = (
                    (self.spec.maximum_position - self.spec.minimum_position)
                    * step_seconds
                    / stroke
                )
                current += math.copysign(min(abs(delta), maximum_change), delta)
        self.position = self._clamp(current, minimum, maximum)
        self.elapsed_seconds += step_seconds

        feedback = (
            active_fault.feedback_stuck_position
            if active_fault.feedback_stuck_position is not None
            else self.position + active_fault.feedback_bias
        )
        feedback = self._clamp(float(feedback), 0.0, 100.0)
        mismatch = abs(feedback - target) > self.spec.command_deadband
        self.mismatch_seconds = self.mismatch_seconds + step_seconds if mismatch else 0.0
        open_proof = self.position >= self.spec.open_proof_threshold
        closed_proof = self.position <= self.spec.closed_proof_threshold
        if active_fault.open_proof_failed:
            open_proof = False
        if active_fault.closed_proof_failed:
            closed_proof = False

        normalized = self._clamp(
            (self.position - self.spec.minimum_position)
            / (self.spec.maximum_position - self.spec.minimum_position),
            0.0,
            1.0,
        )
        leakage = self.spec.leakage_percent
        flow_percent = leakage + (100.0 - leakage) * normalized**self.spec.flow_exponent
        sample = VirtualActuatorSample(
            command=requested,
            effective_target=target,
            physical_position=self.position,
            feedback_position=feedback,
            flow_percent=self._clamp(flow_percent, 0.0, 100.0),
            open_proof=open_proof,
            closed_proof=closed_proof,
            traveling=abs(self.position - target) > self.spec.command_deadband,
            command_feedback_mismatch=mismatch,
            mismatch_seconds=self.mismatch_seconds,
            proof_alarm=(mismatch and self.mismatch_seconds >= self.spec.proof_timeout_seconds),
            command_available=active_fault.command_available,
        )
        self.last_sample = sample
        return sample
