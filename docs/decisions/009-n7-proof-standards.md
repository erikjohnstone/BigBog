# 009: What "proven" means for the native lane (N7)

Status: accepted (N7).

## Context

N6 gave the native lane a Shadow Runtime; N7 had to show that its results mean
something. Four questions came up while building the proofs and each needed a rule
rather than a case-by-case call.

## Decisions

1. **Mutation oracles are layered, and the differential is one of them.** A mutant
   `.bog` is judged validator → loader → acceptance suite → three-way differential
   (`bactalk.niagara.mutate.judge_mutant`). The differential compares the mutant's
   output trajectories with the IR interpreter's and the retained reference inside the
   documented bands (decision 008), so a mutation that no end-of-scenario expectation
   notices is still caught when it changes what the controller does over time. What
   survives all four is a genuine gap in the scenarios, and the survivor list is the
   input to the Test Generation Protocol (N8), not something to explain away.

2. **The catch rate is reported as measured, on a stated sample.** D4 asks for
   ≥ 95 %. `artifacts/native-bog/d4-tier1.json` records, per Tier 1 controller, the
   number of mutants the operators generate, the seeded sample judged, the catch rate
   by operator and by oracle, and every survivor. Neither Tier 1 suite meets the
   target: VAV reheat 63.5 % (its six scenarios never exercise time suppression, CO2
   demand control, the heating-maximum branch or the flow-sensor alarm) and the
   multizone AHU 65.5 %. The AHU's first figure (200 of 200) was an artifact of a
   baseline that failed its own suite, which made every mutant look caught;
   `run_mutation_suite` now refuses such a baseline (N8 finding). The report says
   `target_met: false`; the tests pin the measured floors so a regression is caught
   and do not pretend the target is met.

3. **Shadow Runtime evidence is a qualification job, append-once, and a failing
   scenario fails the candidate.** `qualify_with_shadow` mirrors the BOPTEST and
   Alfalfa lanes: it runs the exact signed `.bog`, writes
   `shadow-verification/evidence.json` (the Shadow Runtime report, the differential and
   the reference trajectories) into the artifact digest, and sets the run to
   `ready_for_review` or `failed`. Approval and export are already refused for a
   failed run, so "export is blocked while any scenario fails" needs no new gate. The
   evidence carries `tier: bog-simulated` and the API never calls it Niagara
   runtime qualification.

4. **Calibration compares aligned traces and ignores the start-up instant.** A
   station's first history record and the operator's t = 0 are not the same instant,
   so `compare_trace` aligns an export by the shift, within two intervals of "first
   record = first expected record", that explains it best, then applies the timing and
   value tolerances. The t = 0 record the Shadow Runtime takes during start-up is not
   part of the expected trace: no operator clock exists for it in a station.

## Consequences

- `tests/test_native_bog_mutation.py` runs a small seeded sample per controller with
  all four oracles and asserts the recorded floors; the full sample is regenerated
  with `scripts/native_bog_proofs.py --only d4`.
- N8's suite generator must raise the VAV reheat catch rate to the target before the
  item is marked done; the survivors in the D4 report are its first work list.
- The web app shows Shadow Runtime evidence beside BOPTEST and Alfalfa with the
  violet simulated marker; the release summary carries `shadow.passed`.
