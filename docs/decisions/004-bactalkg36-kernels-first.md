# 004: The `bactalkG36` module is kernels first, wrappers second, SDK last

Status: accepted (N3). Building and signing the module is Gate G-SDK.

## Context

The lowering matrix (003) needs a Niagara module for 15 IR kinds that no stock
block reproduces. The ProgramObject generator already carried exact Java for
each of them, but baked every parameter in as a constant and wrapped it in
generated `onExecute` glue. CI has a JDK and no Niagara SDK.

## Decision

- **One plain-Java kernel per behaviour**, parameterised at construction, under
  `niagara-module/bactalkG36/bactalkG36-rt/src/com/bactalk/g36/kernel/`. The
  kernels are ports of the ProgramObject kernel members, not rewrites: the same
  arithmetic, the same state, the same monotonic-time contract. Thirteen kernels
  cover the fifteen kinds (`NumericChange` carries three modes; `TrimAndRespond`
  carries the hold variant).
- **Behaviour is pinned twice.** `KernelHarness` drives any kernel from a line
  protocol; `tests/test_native_bog_kernels.py` replays the Open Control Engine
  golden rows already pinned for the generator (PID, Trim-and-Respond, Timer,
  UnitDelay, FirstOrderHold) and runs every kernel against BACTalk's IR
  interpreter on randomised inputs with irregular steps (three seeds each,
  1e-9 tolerance). A kernel that drifts from either fails CI.
- **Component wrappers use the classic slot style**, not the annotation
  processor, so they compile against a small `javax.baja` stub surface in CI
  (`niagara-module/stubs`). `BKernelComponent` owns the execution ticket, the
  time base (seconds since `started()`), and the status policy: any invalid
  input marks the outputs null and does not step the kernel.
- **Gradle mirrors nhaystack** (settings plugins, `-rt` and `-wb` parts,
  `niagara-module.xml`, `module-include.xml`, lexicon, palette as a
  `bajaObjectGraph`). The build refuses the default signing profile.
- **Python knows the module.** `bactalk.niagara.module` declares each
  component's slots and how a block's IR configuration fills its parameters;
  the validator accepts `bactalkG36:*` through `declared_types()`, and tests
  fail when the registry, the Java slots or `module-include.xml` drift apart.
- **Tests that need `javac` are declared, not skipped silently**: conftest
  lists `tool:javac` for the kernel module, so the strict integration tier
  fails without a JDK and CI installs one.

## Consequences

- N4 can emit `bactalkG36:*` components with the correct slot names and
  parameter properties today; whether Niagara loads them is Gate G-SDK.
- The stubs are the smallest surface that compiles the wrappers. Anything the
  real SDK rejects is a finding the gate returns in `findings.md`.
- `Pre` advances only on the execution tick, never on an input change; that is
  the property that makes it a one-tick delay, and the wrapper documents it.
