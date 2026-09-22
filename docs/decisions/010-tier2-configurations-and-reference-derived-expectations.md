# 010: Tier 2 configurations, mechanical scenarios, reference-derived expectations

Status: accepted (N8).

## Context

N8 asks for every LBNL Guideline 36 controller to pass the same four proofs as the
Tier 1 demos. Tier 1 had two controllers with hand-written scenarios cited from the
G36 text (ten cases, a week of engineering). Twenty more controllers, each needing a
complete parameter set and a scenario suite, cannot be hand-written to that standard
without either hiding gaps or stalling the milestone. The source of truth for Tier 2
is, by the goal's own definition, the LBNL controller executed by the Open Control
Engine.

## Decisions

1. **A configuration is a controller plus one complete parameter set.**
   `bactalk.library_tier2.CONFIGURATIONS` lists them: every CDL parameter LBNL leaves
   without a default (design airflows, fan ratios, supply-temperature limits, sensor
   options) plus the variant choices (ventilation and energy standard). The terminal
   units share the box LBNL's own validation uses, so the family differs only in
   logic. Each configuration is retained (translation and reference) under the
   package, like the Tier 1 demos, so a base install can build it.
2. **Scenarios are mechanical.** From the public interface alone: the nominal
   operating point (one table of physically sensible values by port name, SI units),
   then one perturbation per input in interface order (a boolean toggled, a
   temperature 4 K either side, a flow at zero and at twice nominal, every operation
   mode), 45 one-minute scans each. This is protocol rule 3 applied blindly and it
   never looks at the logic.
3. **Expectations come from the reference, inside the D3 band.** Each scenario's
   expected outputs are the retained OCE trajectory's final values with a tolerance
   of 2 % of that output's range over the suite (the D3 value band, decision 008),
   booleans exact. The suite therefore grades the translation against LBNL; it does
   not encode anyone's reading of the guideline. Rows in `docs/coverage.md` say so
   ("reference-derived") to distinguish them from Tier 1's cited expectations.
4. **Adequacy is reported, not assumed.** D4's seeded mutant sample runs for every
   configuration and the catch rate is printed beside it. Mechanical suites will miss
   what their perturbations never reach; those survivors are the work list the Test
   Generation Protocol (N9 onward) inherits, and no configuration is called done at
   D4 below the target.
5. **Requests are project signals with a reducer.** G36 wires equipment with
   request counts that are summed at the receiver. `ProjectSignalAggregation`
   (`sum`, `max`, `any`) joins `ProjectSignalBinding` in the project model; the
   simulator reduces the sources, and the station assembler builds the reduction as
   a chain of `kitControl:Add` (or `Maximum`, `Or`) blocks in a `Requests` folder of
   the receiving program, four inputs per stage, all ordinary links.
   `bactalk.library_tier2.requests` generates the signals from the project's
   `feeds` and `serves` relationships and LBNL's port names; a rule applies only
   when both ends expose matching points.
6. **Blockers are rows, not omissions.** A configuration the translator, the
   importer or the engine refuses is retained as a blocker record
   (`library_tier2/blockers.json`) and appears in `docs/coverage.md` with the exact
   reason, which is what the N8 exit asks for.

## Consequences

- `scripts/retain_tier2.py` regenerates translations, references and blockers;
  `scripts/coverage_report.py` regenerates `artifacts/native-bog/coverage.json` and
  `docs/coverage.md`; tests check that the committed copies match the code.
- Reference-derived expectations are only as good as the nominal table: an
  implausible operating point produces a valid but uninteresting scenario. The
  survivors list shows where that happens.
- The `host_tick_v1` execution profile is the Tier 2 default, as for Tier 1, because
  `CDL.Logical.Pre` has no exact same-instant equivalent in the host-tick lowering.
