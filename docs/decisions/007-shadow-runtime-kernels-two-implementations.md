# 007: The Java kernels are the truth; a Python port runs without a JVM

Status: accepted (N6).

## Context

The Shadow Runtime executes `bactalkG36` components. The Java kernels from N3
are what the real module runs, so the runtime must reproduce them exactly. A
base install of BACTalk has no JVM, and the web workers should still be able to
shadow-run an export.

## Decision

- **Two implementations of one contract.** Each kernel exists as Java
  (`niagara-module/bactalkG36/bactalkG36-rt/src/com/bactalk/g36/kernel`) and as
  a field-for-field Python port (`bactalk.niagara.shadow.kernels`). The Java
  source is authoritative: a behavioural change is made in Java first and ported.
- **Provable both ways.** `python -m bactalk.niagara.shadow check` drives every
  kernel through both implementations on random walks at irregular steps,
  including repeated instants, and any differing double or boolean fails.
  `tests/test_native_bog_shadow_kernels.py` runs the same check when a JDK is
  present, and always runs the Python ports against the OCE goldens and the IR
  interpreter that pin the Java kernels. CI installs a JDK, so a drift fails the
  build.
- **Backend selection.** `ShadowRuntime(kernel_backend="auto")` uses the JVM
  sidecar (`KernelHarness` session protocol, one process per run) when `java`
  and `javac` are available and the Python ports otherwise; `"python"` and
  `"jvm"` force either. Reports record which backend ran.
- **Wrapper semantics are part of the contract.** How a component steps
  (`executionPeriod`, on input change, tick-only for `Pre` and `NumericChange`,
  null outputs on invalid inputs) is defined by `BKernelComponent` and mirrored
  by `bactalk.niagara.shadow.blocks.ModuleBlock` (S-MODULE-1..5 in
  docs/niagara-semantics.md).

## Consequences

- N6 changed three kernels in both implementations (MovingAverage checkpoints,
  same-instant sampling in UnitDelay, FirstOrderHold and TrimAndRespond); the
  goldens still pass and both implementations agree.
- The JVM sidecar is slower than the Python ports (one pipe round trip per
  kernel step); the performance target for a project (AHU plus 25 VAVs) is met
  with either backend through the process-pool fan-out, and the worker path
  chooses `auto`.
