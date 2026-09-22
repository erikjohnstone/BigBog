# 011: The Test Generation Protocol (N9)

Status: accepted (N9). Applies to every Tier 3–5 item; Tiers 1–2 keep decisions 008–010.

## Context

Tiers 3 and up have no LBNL reference model, so "correct" has to be stated somewhere
that is neither the logic nor the tests. GOAL-NATIVE-BOG.md's protocol says how: a
numbered, cited requirement set; strict separation of the logic author and the test
author; tests built mechanically from the requirements; adequacy proven by mutation,
decision coverage and randomised invariants; disagreements classified and only the
ambiguous ones raised to a human; a readable test plan in the approval digest.
`bactalk.protocol` implements it; `bactalk.library_tier3` holds the first item, the hot
water plant (`hw-plant-boiler`).

## Decisions

1. **Requirements are data with a digest.** `RequirementSet` (`bactalk.protocol.requirements`)
   is a JSON document: points with ranges and resolutions, requirements with conditions
   on inputs, timing (delay, release, what the delay counts from, scans of tolerance),
   outcomes on outputs, `otherwise`/`before`/`recovery` states, stated failure behaviour
   per input, and invariants. Every requirement cites its source with a fidelity
   (`verbatim`, `paraphrase`, `designer`). The canonical digest is what Gate G-ENG
   approves and what every scenario and the exported job (`sequence.parameters.protocol`)
   reference.

2. **Separation is enforced in code, not by convention.** `bactalk.protocol.test_author`
   imports the requirement model and the acceptance-case schema only;
   `tests/test_protocol.py` parses its import list and fails on any import of the
   simulator, the Niagara packages or a library job. The logic author
   (`library_tier3/<item>/graph.py`) never imports the test author or the plan.
   Traceability is in the graph's `metadata.traceability` (block id → requirement ids)
   and the test checks that every requirement is implemented by at least one block and
   tested by at least one scenario.

3. **Scenarios are mechanical.** Per requirement: positive, negative, one condition
   false at a time, one scan either side of every delay and release window, both edges
   of every threshold, both edges of every deadband, every stated failure behaviour
   (fault injection: stuck, stale, forced out of range) with recovery, and recovery
   after the conditions clear. Inherited conditions (`assumes`) are context kept
   satisfied; a requirement with no conditions of its own is driven through its
   context. Measured facts the arithmetic rests on: the acceptance runner primes every
   phase with a zero-length scan, so a window of D seconds has elapsed after D / step
   repeats; a per-second runtime sees a delay elapse up to one scan after a per-scan
   interpreter (`tolerance_scans` = 1 on every timed requirement of the plant); trim
   and respond applies its first reset at the first sample-period boundary after the
   delay measured from plant enable (`timing.reference = "context"`); a runtime
   accumulator behind a `Pre` block lags two scans (rotation `tolerance_scans` 2–3).

4. **Unstated behaviour is a question, never an assumption.** Where the requirement
   set does not say what an output does (no `otherwise`, no failure behaviour for an
   input) the author records a gap instead of inventing an expectation; the gaps are
   listed in the plan and in the web app as questions for the engineer.

5. **Adequacy is measured on four legs and accepted on all of them.** Every scenario
   passes on the interpreter; every typed decision saw both outcomes; every invariant
   held on every step of every scenario and across ≥ 10 000 randomised input sequences
   (values inside the declared ranges, mostly held between steps, sometimes a hair
   either side of a threshold the requirements name); the Shadow Runtime agrees with the
   interpreter inside the bands; and a seeded sample of mutants of the exported `.bog`
   is caught at ≥ 95 %. The report (`adequacy.json` beside the requirements) records
   each leg as measured, accepted or not.

6. **The scan leg.** A Niagara station ticks module kernels every second. The plant's
   rotation requirements run for days of simulated time, which a per-second Shadow
   Runtime cannot judge 200 times over. The differential and the mutation sample
   therefore run under `scan-module-tick` (`ExecutionPolicy.module_period_seconds = 0.0`,
   resolved per case to its scan) with the `scan` band set: the coarse leg's value
   tolerance and three scans of timing slack, because every module kernel in a chain
   ticks once per scan in document order and the plant's `Pre → TimerAccumulating →
   SetReset` chain lands an edge up to three scans later than the IR (measured). The
   per-second leg is run once for the retained artifact when time allows
   (`--d3-default`) and recorded beside it; the coverage report shows both. This
   extends decision 010 item 8 (D4 judged on the leg the baseline passes) with a leg
   chosen for cost, named in the artifact.

7. **Classification is rule-based.** The protocol's third step is deterministic:
   a scenario that contradicts itself or rests on an unreachable condition is a test
   bug; a failure at a threshold, a timing edge or a deadband edge is an ambiguous
   requirement and becomes a question; anything else is a logic bug. No model is
   consulted; when one is, it slots in behind the same `Classification` record.

8. **Gate G-ENG binds approval and export.** `WorkbenchService.approve` and every
   export path refuse a job whose `sequence.parameters.protocol` digest has no retained
   approval (`RequirementApprovalRepository`, one record per digest, append-only). The
   API exposes the requirement sets, the generated plan, the adequacy report, the
   readable test plan and the approval (`/api/protocol/sequences`); the web app's
   Libraries → Requirements page is where the engineer reads and approves.

9. **Findings.** (a) `pi_loop` with a linked `direct` input cannot lower: the matrix
   maps `direct` to the stock LoopPoint's `loopAction`, which is an enum property, so
   the validator refuses the link and the Shadow Runtime has no such slot. Tier 3 uses
   `pid_with_reset` (P form, `reverse_acting`) for its loops; the `pi_loop` row needs a
   constant-folding rule or a module before a Tier 3 item may link `direct`.
   (b) `coarse-module-tick` is a fixed 60 s period, right for Tier 2's 60 s scans and
   wrong for anything else; hence the scan policy. (c) The suite driver constructed one
   runtime per case with the raw policy, so a policy resolved per case had to be
   resolved in both `run_shadow_case` and `run_shadow_suite`.

## Consequences

- A Tier 3 item is done when `docs/coverage.md` lists it with D1–D4 measured, the
  adequacy report accepted, and Gate G-ENG approved; the first two are the
  repository's, the last is a person's.
- The requirement set is the contract: changing it changes the digest, invalidates the
  approval and the retained adequacy artifact, and regenerates every scenario.
- The scan leg is a stated weakening relative to the per-second leg; the per-second
  leg stays the one that speaks for a Niagara station, and it is retained whenever run.
