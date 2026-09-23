# 016: The module Pre at startup, CDL time tables, and CDL substitutes for LBNL's equation utilities

Status: accepted (N8 follow-up). Builds on decisions 007, 010, 011 and 015.

## Context

Decision 015 left three items open:

- the `bactalkG36:Pre` startup lag that blocked the economizer's D4;
- `CDL.Logical.Sources.TimeTable`, which blocked `Enabling.Enable`;
- the Tier 2b rows built on LBNL utilities written as Modelica equations or
  algorithms, which the Open Control Engine cannot execute.

## Decisions

### Startup (S-MODULE-7)

1. **Every module component executes once at station start.** The Java wrapper
   (`BKernelComponent`) used to schedule its first execution one `executionPeriod`
   after start. The Shadow Runtime, following S-LINK-2, executed every component in
   the start pass. The two disagreed, and neither matched CDL at t = 0. The wrapper now
   schedules a zero-delay `startExecute` ticket from `started()`, after the links have
   delivered their start values. That is what the Shadow Runtime models.
2. **A kernel whose first output ignores its input latches the settled start input.**
   `Pre`, `BooleanInitialization` and `SampleTrigger` execute first in the start pass,
   because their output does not depend on their input. They therefore used to latch
   an input that had not settled. At the end of the start instant (a late zero-delay
   timer in the Shadow Runtime, a zero-delay `latch` ticket in Java), such a kernel is
   rebuilt and stepped once more with the settled inputs. Its output is unchanged, and
   it now holds the t = 0 input, as CDL's `Pre` does. Kernels that already resample at
   the end of an instant (`UnitDelay`, the integrator, the counter) re-step through
   S-MODULE-6 and need nothing more.

   `tests/test_native_bog_shadow_blocks.py::test_pre_latches_the_settled_start_input`
   fails without the change and passes with it. The ticket order relative to link
   activation rests on S-LINK-2, which calibration case `s-status-6` checks.
3. **Every graded row is regraded.** The change touches every row with a `Pre`, so the
   coverage cache is invalidated (`GRADING_VERSION` 4) and the whole report is
   regenerated.

### Time tables

4. **A constant schedule column becomes a constant.** The engine implements CDL's
   Boolean, Integer and Real `TimeTable`, but its CXF subset refuses any instance whose
   port count comes from a parameter. So a time table cannot sit inside a composite,
   whatever the shape of its table. The array scalariser now rewrites each output
   column:
   - A column that holds one value in every row is that value at every time; the
     row selection never matters. It becomes a `Sources.Constant`, using the engine's
     own reading: `floor(v + small)` for Integer and Boolean tables, and the offset
     added for Real tables.
   - A column that varies is refused with that reason. A time-varying schedule needs a
     schedule kind in the IR and a module kernel keyed to the station clock; the
     engine's `Pulse` has different boundary rules (a 1 µs tolerance against rounding
     to six decimals), so rewriting a schedule into pulses would not be exact.

   LBNL's `Enabling.Enable` validation instance and the template's default both use
   `[0, 1; 24*3600, 1]`, enabled all day, so the row retains. The array evaluator also
   gained Modelica's matrix literal `[a, b; c, d]`.

### CDL substitutes

5. **BACTalk writes CDL block diagrams for five LBNL utilities.** These are the
   utilities written as equations or an algorithm:
   - `Initialization` is `Switch(Pre(true), u, yIni)`. The engine's `Pre` is false on
     the first evaluation only, which is `initial()` under host-tick execution.
   - `TimerWithReset` must restart on a rising `u` or a rising `reset`, even on
     consecutive evaluations. A toggle flips on every restart, and two
     `TimerAccumulating` blocks are reset on its rising and falling edges, so each
     restart is a clean edge for exactly one of them, and the toggle selects the timer
     it cleared. `passed = u and elapsed >= t`, or'ed with the source's initial
     `passed = t <= 0`, which holds until the first when-clause event.
   - `MultiMaxInteger` and `MultiMinInteger` convert to Real, take `MultiMax` or
     `MultiMin`, and round back. This is exact: the result is one of the Integer inputs.
   - `TrueArrayConditional` computes the algorithm's loop in closed form. Position `i`
     sets `y1[uIdx[i]]` when its index is valid and the number of valid positions up
     to and including `i` is at most `u`. Duplicate and out-of-range indices count
     exactly as they do in the loop.

   The sources are `src/bactalk/integrations/cdl_substitutes/BACTalk/CdlSubstitutes/*.mo`.
   `scripts/build_cdl_substitutes.py` translates them with the pinned modelica-json,
   renames each to the class it replaces, and commits the CXF with a manifest of both
   digests. `--check` re-translates and fails on any difference.
6. **Each substitute is checked against LBNL's source, not against BACTalk.**
   `tests/test_cdl_substitutes.py` runs the engine on each substitute over seeded input
   sequences, with events on consecutive ticks, repeated and out-of-range indices, and
   thresholds above, at and below zero. It compares every output on every tick with a
   reference written from the Modelica source: the `initial()` equation, the `when`
   clauses (read tick by tick; a when-clause does not fire at initialization), `max`
   and `min`, and the algorithm statement by statement.
7. **Substitution is visible.** `PlantControlsCdlLibrary` offers the substitutes as class
   documents. LBNL's equation classes emit no block diagram, so nothing is displaced;
   a controller that is itself one of the five uses its substitute as the root. Every
   translation and execution names the substitutes it used (`cdl_substitutes`), and the
   retained translation records them.
8. **BACTalk's own `TimerWithReset` was wrong at initialization for `t <= 0`.** The
   interpreter, both kernel ports and the generated ProgramObject set
   `passed = u and t <= 0` on the first tick. LBNL's initial equation is
   `passed = t <= 0`, whatever `u` is. All four now follow the source. Every LBNL use has
   `t > 0`, and the Java and Python kernels still agree on all 7,920 equivalence rows.

### Pipeline fixes the unblocked rows needed

9. **A child that reads its own output** (`connect(y1Coo, preMod.u)` in `ModeControl`)
   puts the output, its driver and the reader in one connection set. The engine
   resolves that at the root but refuses it inside a nested composite. The assembler now
   wires such readers to the output's internal driver when it normalises a child.
10. **A modification that passes the plant's application enum to a child**
    (`final typ=typ`) now receives the enum member. The child grounds its own
    expressions from it. The compile-time grounder used to refuse it as an unresolved
    dependency.
11. **Array evaluation.** Nested comprehensions such as
    `{{staEqu[i, j] for i in 1:nSta} for j in 1:nEqu}` now evaluate, as does
    two-dimensional indexing.
12. **An Integer vector replicator** in a replicator-only composite gets
    `Integers.AddParameter(p = 0)` identities, like the Real one.
13. **`MultiSum` gains were dropped. Two committed rows were wrong, and are corrected.**
    The scalariser folded `MultiSum` into additions without ever reading its gain
    vector `k`. Two LBNL chiller-plant sums set it:
    - `Economizers.Subsequences.Tuning.mulSum`, `k = {-step, step, 1}`;
    - `Towers...IntegratedOperation.totMinCycLoa`, `k = fill(1.1, nChi)`.

    The engine ran BACTalk's scalarised CXF, so the retained references of
    `chw-economizer` and `chw-towers` carried the same error. D2 and D3 agreed because
    both sides were the same wrong program. This surfaced because I first made the fold
    refuse gains it did not expand, and the drift check then refused exactly those two
    rows. An input whose gain is not 1 now passes through a `MultiplyByParameter`
    before the fold. Integer gains are still refused, since no LBNL controller uses
    them. Both rows are re-retained, and
    `tests/test_cxf_array_expressions.py::test_multisum_gains_are_applied_not_dropped`
    pins the gains in the committed IR.

    The economizer's period-two limit cycle, which decision 015 item 23 attributed to
    LBNL's reference, was this bug. With the gains the tuning parameter settles one
    step at a time. The "no end-of-scenario value inside a limit cycle" rule was
    removed, and every output again gets its expectation.

    I audited every other expanded construct for a parameter its expansion does not
    read, and found none. In this CDL version the extractors have only `nin`, and the
    vector filter reads `msk`, the limiter `uMax`/`uMin`, `Sort` `ascending`, the matrix
    reductions `rowMax`/`rowMin`, and `ExtractSignal` `extract`.
14. **`EquipmentEnable` supplies `nEquAlt = 2`.** That is LBNL's default binding for its
    validation `staEqu` (the most part-load units in any stage). The row says so,
    because BACTalk does not evaluate a `max` over `sum` comprehensions.

## What remains blocked

- `StageIndex` and `EquipmentAvailability`, and the controllers built on them
  (`Pumps.Generic.StagingHeadered`, `HeatPumps.AirToWater`), are `Modelica.StateGraph`
  machines: steps, prioritised and timed transitions, and event iteration within an
  instant. A CDL rewrite that matches StateGraph's discrete semantics is a design of
  its own, and they stay listed with that reason.
- The full `Plants.Chillers.Controller` still stops at LBNL's algebraic loop
  (decision 015 item 16).
- A time-varying `TimeTable` needs a schedule kind.

## Consequences

RESULTS

Nothing here is Niagara runtime qualification. Gates G-SDK, G-WB and G-ENG remain
with people.
