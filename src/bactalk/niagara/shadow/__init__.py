"""Niagara Shadow Runtime (GOAL-NATIVE-BOG.md N6).

Loads an exported ``.bog`` and executes it with Niagara-like semantics: status
values, writable priority arrays, event-driven link propagation, timed and
periodic blocks on a simulated clock, and the ``bactalkG36`` kernels through a
JVM sidecar or their Python ports. The file is the runtime's only input; it
never reads BACTalk's IR. Every semantic assumption is listed with its source
in ``docs/niagara-semantics.md``.
"""

from bactalk.niagara.shadow.blocks import REGISTRY, known_types, make_kernel_backend
from bactalk.niagara.shadow.driver import (
    ENGINE_PREFIX,
    RobustnessReport,
    ShadowDriverError,
    ShadowRunOptions,
    run_shadow_case,
    run_shadow_suite,
    run_under_policies,
)
from bactalk.niagara.shadow.engine import PropagationLoopError, ShadowRuntime
from bactalk.niagara.shadow.loader import Program, ShadowLoadError, load_program
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, PLAUSIBLE_POLICIES, ExecutionPolicy
from bactalk.niagara.shadow.status import Status, StatusValue

__all__ = [
    "DEFAULT_POLICY",
    "ENGINE_PREFIX",
    "PLAUSIBLE_POLICIES",
    "REGISTRY",
    "ExecutionPolicy",
    "Program",
    "PropagationLoopError",
    "RobustnessReport",
    "ShadowDriverError",
    "ShadowLoadError",
    "ShadowRunOptions",
    "ShadowRuntime",
    "Status",
    "StatusValue",
    "known_types",
    "load_program",
    "make_kernel_backend",
    "run_shadow_case",
    "run_shadow_suite",
    "run_under_policies",
]
