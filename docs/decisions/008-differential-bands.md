# 008: Tolerance bands for the three-way differential

Status: accepted (N7, D3).

## Context

D3 compares three trajectories per output and scenario: the exported `.bog` in
the Shadow Runtime, BACTalk's IR interpreter, and the source of truth (for Tier
1 the LBNL controller executed by the Open Control Engine, retained under
`src/bactalk/library_demo/references/`). The interpreter and the reference agree
to floating-point noise apart from one-scan timing of threshold-driven
integers; the Shadow Runtime differs from both for one structural reason: the
`bactalkG36` components execute every `executionPeriod` (1 s) while the
interpreter and the reference step once per scan (60 s in the retained suites).
An explicit-Euler PID integrated sixty times per scan leads the once-per-scan
one by up to a scan of integral action, and every request count, alarm level
and edge derived from a threshold on such a signal moves by up to two scans.

## Decision

`src/bactalk/niagara/bands.json` carries two band sets, both pyfunnel funnels
(`atolx` seconds around the reference time, `atoly` around its value):

- **`default`** (the engineering band, applied to the Shadow Runtime under its
  default policy): numeric signals 2 % of the signal's range over the scenario
  (never below 1e-6) and two scans of time; booleans and integers exact in value
  and two scans of time. One scan of integral action at the Tier 1 loop gains
  measures 1.1 % of range on the damper loop, which is what the 2 % covers.
- **`coarse`** (applied to the Shadow Runtime under the `coarse-module-tick`
  policy, where every module component steps once per scan like the
  interpreter): numeric signals 0.1 % of range (never below 1e-9) and one scan;
  booleans and integers exact and one scan, the same one-scan ordering slack the
  interpreter and the Open Control Engine need between themselves. This leg
  proves the residual difference under the default policy is discretisation
  and nothing else.

Both legs must pass for D3 to pass. Widening either set, or adding a per-signal
override to `bands.json`, needs a new decision record with the engineering
rationale; the differential report names the band set and rationale it applied
to every signal, so a widened band is visible in the artifact.

## Consequences

- N7 found and fixed two runtime-facing kernel defects while establishing the
  bands: `PIDWithReset` and the unit delay inside `TrimAndRespond` were not
  idempotent within one instant (an input change followed by the period tick
  showed the post-integration value), and the stock edge, latch, sampler and
  hysteresis lowerings reacted to transient values inside one link propagation.
  Those kinds are now tick-semantic `bactalkG36` components (docs/decisions/003
  matrix rows updated, `docs/niagara-lowering-matrix.md`).
- The AHU demo job now sets the design outdoor-air parameters
  (`VDesOutAir_flow`, `VAbsOutAir_flow`, `VDesTotOutAir_flow`,
  `VUncDesOutAir_flow`); with the LBNL defaults of zero the controller divides
  by zero in every engine and the trajectories are not comparable.
