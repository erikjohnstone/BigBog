"""Execution-order and timing policies (docs/niagara-semantics.md, "Uncertainty").

Where Niagara's exact behaviour is ``ASSUMED`` the runtime makes it a policy
knob, and the robustness suite runs every scenario under several plausible
policies; a result that depends on the knob is a finding, not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from bactalk.niagara.shadow.status import Status


@dataclass(frozen=True)
class ExecutionPolicy:
    name: str = "default"
    link_order: str = "document"
    """Order in which one changed output fires its links: document, reverse or shuffle."""

    tick_order: str = "topological"
    """Order of timers due at the same instant: topological, document, reverse or shuffle."""

    propagation: str = "depth"
    """depth: a fired link's consequences run before the next link; breadth: after."""

    seed: int = 0
    module_period_seconds: float | None = None
    """Override every bactalkG36 executionPeriod (None keeps the file's value, default 1 s)."""

    one_shot_pulse_seconds: float = 0.5
    """kitControl:OneShot pulseWidth when the file does not set it (S-ONESHOT-2)."""

    loop_execute_seconds: float = 0.5
    """kitControl:LoopPoint executeTime when the file does not set it (S-LOOP-2)."""

    loop_disabled: str = "hold"
    """LoopPoint output while loopEnable is false: hold, minimum or bias (S-LOOP-5)."""

    multivibrator_initial: bool = True
    """kitControl:MultiVibrator output at station start (S-MV-2)."""

    start_order: str = "topological"
    """Order of the one-time execution at station start (S-LINK-2).

    One of topological, document, reverse or shuffle.
    """

    inputs_before_timers: bool = True
    """At a scan boundary, apply new inputs before timers due at that instant fire."""

    propagate_flags: Status = Status.OK
    """kitControl propagateFlags default when the file does not set it (S-STATUS-4)."""

    loop_limit: int = 1000
    """Executions of one component within a single propagation before it is a loop."""

    def variant(self, name: str, **changes: object) -> ExecutionPolicy:
        return replace(self, name=name, **changes)  # type: ignore[arg-type]


DEFAULT_POLICY = ExecutionPolicy()

PLAUSIBLE_POLICIES: tuple[ExecutionPolicy, ...] = (
    DEFAULT_POLICY,
    DEFAULT_POLICY.variant("reverse-links", link_order="reverse", tick_order="reverse"),
    DEFAULT_POLICY.variant("shuffled-1", link_order="shuffle", tick_order="shuffle", seed=1),
    DEFAULT_POLICY.variant("breadth", propagation="breadth"),
    DEFAULT_POLICY.variant("timers-first", inputs_before_timers=False),
    DEFAULT_POLICY.variant("coarse-module-tick", module_period_seconds=60.0),
    DEFAULT_POLICY.variant("long-pulses", one_shot_pulse_seconds=2.0, loop_execute_seconds=1.0),
    DEFAULT_POLICY.variant("document-start", start_order="document"),
    DEFAULT_POLICY.variant("document-ticks", tick_order="document"),
    DEFAULT_POLICY.variant("multivibrator-low", multivibrator_initial=False),
)


__all__ = ["DEFAULT_POLICY", "PLAUSIBLE_POLICIES", "ExecutionPolicy"]
