# 015: Arrays across composites, the chiller-plant subsystems, and Tier 2b

Status: accepted (N8 follow-up). Builds on decisions 001, 010 and 014.

## Context

Decision 014 left the G36 chiller plant's staging, pump, cooling-tower and economizer
subsystems, and the full `Plants.Chillers.Controller`, blocked where arrays cross
composite boundaries. GOAL-NATIVE-BOG.md N8 also asks for Tier 2b: the LBNL
`Templates.Plants.Controls` controllers through the same native lane, each passing
D1–D4 or listed with its exact blocker.

The Open Control Engine refuses array connectors, array instances and array parameters
inside a composite document. So a composite that holds any array must be scalarised
completely, including one that contains child composites, and the child's split ports
must carry the names the parent uses.

## Decisions

### Arrays and composites

1. **Child composites are opaque blocks with known ports.** `child_port_oracle` reads a
   child's class document and resolves its port directions and shapes in the child's
   own scope: the instance's modifications, grounded in the parent, over the class
   defaults. The array scalariser then treats the child as a block. Its array port
   `c.p` splits into `c.p__1…n`, exactly as the child's own pass splits its boundary.
   The assembler keeps the parent's edges on those split ports when it merges the
   child's nodes.
2. **Any composite holding arrays is scalarised.** Before this change, only composites
   with a reduction or filter were scalarised. A composite with array connectors or
   array instances, but no such construct, was left for the engine to refuse.
3. **Arrays of composite instances** (`heaPreCon[nChi]`) become one instance per
   element. Each element gets element `i` of every modification: from `fill(expr, n)`
   the expression itself, from a brace literal its element, and from the name of an
   array parameter its element. A scalar modification applies to every element, as
   Modelica's `each` does. **Arrays of elaborated constructs** (`intRep1[nSta]`) are
   pre-expanded the same way, and their endpoints are recombined under the array's
   name. An element reference with a partial index (`inst.y[2]`) selects that
   instance's whole vector.
4. **New array constructs.** Real, Boolean and Integer extractors expand to a switch
   chain that reproduces `u[min(nin, max(1, index))]`. MatrixMax and MatrixMin fold
   per row or column. `Reals.Sort` expands to the compare-exchange sequence of
   Modelica's shellsort. Swaps happen only on a strict comparison, so values and
   source indices match the engine's, ties included, for inputs without NaN. Integer
   and vector replicators are also expanded inside larger composites. A
   replicator-only composite keeps its dedicated expansion, so no retained translation
   moves.
5. **Array expressions are grounded where they are written.** A composite's array
   parameters are evaluated in its own scope before they are handed to a child. One
   array may be built from another, so evaluation repeats until nothing more grounds.
   An opaque child's array modification is also grounded in the parent. The evaluator
   covers:
   - Modelica `if … then … else` chains;
   - comparisons and Boolean operators;
   - enumeration literals, and indexing into grounded arrays;
   - multi-iterator comprehensions, where the last iterator is outermost, as in
     `{j for i in 1:nChi, j in 1:nSta}` for a `[nSta, nChi]` matrix;
   - multi-dimensional `fill`;
   - `sum`, `size`, `min` and `max`, including over row and column slices.
6. **Derived parameters that read arrays or enumerations are grounded before
   conditional pruning.** Examples are `anyVsdCen = sum({if chiTyp[i] == … then 1 else 0
   for i in 1:nChi}) > 0`, `conInt2(k=size(staMat, 2))` and `con3(k=not
   (have_modPosChiVal and chiIsoValTyp == …TwoPosition))`. Only expressions naming such
   a parameter are touched. The guard resolver also evaluates a derived Boolean such as
   `need_heaPreCon` by expanding its expression.
7. **Enumerations.** The engine grounds `Buildings.Controls.OBC.ASHRAE.G36.Types.*` and
   `Buildings.Controls.OBC.CDL.Types.*` itself. For any other enumeration, BACTalk
   grounds the expressions that read it, then removes the declaration once nothing
   reads it; the chiller plant's `Types.Actuator` is one example. An enumeration-typed
   array parameter that modelica-json emits untyped, or drops (`chiTyp`), is recovered
   from its source declaration: an array label keeps its dimensions, and a declaration
   without a default becomes a required job parameter. Documents the engine already
   read are unchanged: the translations of all 27 earlier rows are byte-identical in
   their CXF.
8. **Modifications are evaluated in the enclosing scope.** An example is `final
   have_WSE=have_WSE and not have_airCoo`. A child's same-named parameter no longer
   shadows the parent's while its modification is evaluated.
9. **Pass-through composites are inlined.** `Utilities.PlaceholderLogical` with
   `have_inp = true` loses its only block to pruning and keeps `connect(u, y)`. A
   composite with no blocks is a wire, not a composite, to the engine. Its drivers are
   connected straight to what its ports reach.
10. **Unsized multi-dimensional parameters** (`staMat[:, :]`) take the supplied value's
    shape when its rank matches the declaration. **Parameters typed with Modelica SI
    units** (`Modelica.Units.SI.Time`) are Reals.

### New blocks

11. **Three new IR kinds and bactalkG36 module kernels.**
    - `numeric_integrator_with_reset` implements CDL `Reals.IntegratorWithReset`: a
      forward-Euler step over the tick, with a reset on a rising trigger.
    - `numeric_on_counter` implements CDL `Integers.OnCounter`: it counts rising
      triggers after its first tick, and a rising reset returns it to its start.
    - `wet_bulb_temperature` implements CDL `Psychrometrics.WetBulb_TDryBulPhi`, Stull's
      closed form.

    The first two emit the state the previous tick left, as the engine does. They are
    feedback kinds: they break a loop, and the interpreter updates them after the tick.
    `FEEDBACK_KINDS` in `bactalk.domain` is now the single list the validator, the
    topological order, the interpreter and the wiresheet all read. Their module kernels
    resample at the end of an instant and recompute from that instant's inputs, so
    nothing is integrated or counted twice.

    The wet-bulb kernels use fdlibm `atan`: Java `StrictMath`, the engine's `libm`, and
    a line-for-line Python port. The `rh^1.5` term is `rh·sqrt(rh)` in both ports. Java
    and Python agree bit for bit on all 7,920 equivalence rows.
12. **Importer.** The importer now maps `Integers.Greater`, `GreaterEqual` and `Less`;
    `Integers.AddParameter`; `Logical.TimerAccumulating` (onto the existing kind); and
    the CDL constants `eps` and `small`.
13. **The source-package lane stops calling module kinds stock.** Its ProgramObject
    builder labelled every block without a ProgramObject `qualified_stock_or_boundary`.
    That label was false for LimitSlewRate and Round, both added in decision 014, and
    for the new kinds. All five now get a generated ProgramObject and standalone Java
    kernel, tested value for value against the Shadow Runtime kernels. The older kinds
    `one_shot`, `numeric_increased` and `numeric_decreased` have the same gap in that
    lane, Tier 1 included. That predates this work and is recorded in STATUS.md, not
    fixed here.

### Scenarios and rows

14. **Step scenarios.** A configuration may declare events. The nominal point holds
    until a scan, and the changes apply from the next scan on. A timeline case with the
    same 45-scan grid carries the event through retention, the job and the
    differential. Chiller staging only starts on a change of the stage setpoint, so the
    staging rows step it (up: 1 → 2; down: 2 → 1). The setpoint row steps the load,
    the pump row the flow, and the economizer row the wet bulb.
15. **Eight new chiller-plant rows.** They cover the economizer, chilled-water pumps,
    condenser-water pumps, towers, staging setpoints, staging up, staging down, and the
    full controller. They come from the pre-release master checkout, and the UI and
    `docs/coverage.md` label them **pre-release**. LBNL ships 0.5 s integral times,
    which flip every loop between its limits on a 60 s scan. The pump, tower and
    economizer rows set 120 s and say so in their descriptions.
16. **The full `Plants.Chillers.Controller` is blocked, and the block is LBNL's.**
    Every stage of our pipeline now passes, and the engine refuses the program:

    > algebraic loop detected: 68 connector(s) form a cycle not broken by a
    > state-holding block (CDL §7.16)

    The loop is in LBNL's source, wire for wire (Controller.mo lines 1841–2289):
    staging (`chiStaUp` latch) → `chiEnaPla` → `disChi.uChi` → `disChi.yChiWatPum` →
    `chiWatPlaRes.uChiWatPum` → plant reset → `chiWatSupSet.TChiWatSupSet` →
    `staSetCon.TChiWatSupSet` → `iniSta.triSam1` (TriggeredSampler) → `staSetCon.ySta`
    → `dowProCon` → `chiStaUp.clr`. Of the `Pre` blocks the controller declares,
    `chiEna[nChi]` sits on the other branch of `chiEnaPla.y`, not on this path. A
    triggered sampler feeds through at its trigger instant, so under CDL's rule this is
    an algebraic loop. Inserting a delay would change LBNL's semantics, so the row is
    listed with that blocker.

### Tier 2b

17. **Tier 2b goes through the plain CDL lane.** `PlantControlsCdlLibrary` keeps every
    class document and always takes the CXF path. `PlantControlsLibrary` keeps
    utilities opaque and substitutes hand-written graphs for its source-package lane.
    Those graphs are verified against their own source audit, not against an
    independent engine run of LBNL's CDL. Tier 2b needs the independent run. There is
    one row for each of the 38 controllers the plant library wires (GOAL-NATIVE-BOG.md
    N8), with `tier = "2b"`, `source = "templates"` (the tagged release) and the
    parameters of an LBNL validation-model instance, named in the row's variant.
18. **A reference must come from the engine.** For a class on the reviewed-composite
    list (`Initialization`, `TimerWithReset`, `PIDWithEnable`, …),
    `G36Library.execute` falls back to BACTalk's own typed-IR interpreter when the
    engine cannot load it. That is not an independent reference, and D3 would compare
    the interpreter with itself. `retain_tier2.py` now refuses any runtime other than
    the Open Control Engine and records the row as a blocker. All earlier references
    were engine runs already.
19. **More general CDL work the templates needed.** None of it is template-specific.
    - `Routing.*ExtractSignal` expands to one wire per output element
      (`y[i] = u[extract[i]]`).
    - A comprehension whose body is a whole array (`{idxEquAlt for i in 1:nEquAlt}`)
      repeats the array as a row.
    - Derived Boolean parameters (`have_pumChiWatPri = have_chiWat and (...)`) are
      grounded in the scalariser's scope and in the parent scope the child-port
      oracle reads. Only expressions that resolve to a Boolean are replaced, so
      numeric parameters keep their literal form.
    - An array dimension may be an expression, with or without the parentheses
      modelica-json sometimes drops (`[if have_pumChiWatPri then nPumChiWatPri else
      nPumHeaWatPri]`). A declaration whose `:` dimensions modelica-json left out
      (`staEqu[:, nHp]`) takes their size from the supplied value.
    - The conditional-guard resolver follows aliases (`final have_pumHeaWatPri =
      have_heaWat`) instead of treating the name as opaque.
    - A boundary output fed straight from a boundary input no longer gets a self-edge,
      either when a pass-through placeholder is inlined or from the engine's resolved
      topology, which names such an output as its own driver.
20. **Exact blockers.** A blocked row's reason names its cause. `retain_tier2.py` reads
    the controller's class closure from source and flags each class that is not a CDL
    block diagram: an equation section holding anything but `connect`, an `algorithm`
    section, or `Modelica.StateGraph`. `MultiMaxInteger` and `MultiMinInteger` are
    equations, but inside a composite the scalariser rewrites them to CDL folds, so
    they block only as standalone rows. Engine rejections are summarised by the
    classes and constructs they name. When composite assembly stops at such a class,
    the error names that class instead of the children left unexpanded.
21. **What Tier 2b retains and what it does not.** 22 of the 38 retain with engine
    references. 15 are blocked because they are, or contain, classes that are not CDL
    block diagrams:
    - `TimerWithReset` (a `when` equation): FailsafeCondition, StageChangeCommand,
      Pumps.Generic.StagingHeaderedDeltaP;
    - `Initialization` (`initial()`): Pumps.Primary.DisableDedicated and
      HeatRecoveryChillers.Controller, which contains it;
    - `TrueArrayConditional` (an algorithm): EquipmentEnable;
    - `StageIndex` and `EquipmentAvailability` (`Modelica.StateGraph`): the rest of the
      staging stack, Pumps.Generic.StagingHeadered and HeatPumps.AirToWater;
    - the rows for `Initialization`, `TimerWithReset`, `TrueArrayConditional` and
      `StageIndex` themselves, plus `MultiMaxInteger` and `MultiMinInteger` standing
      alone.

    These remain available through the source-package lane, whose hand-written graphs
    have their own evidence. The sixteenth, `Enabling.Enable`, is BACTalk's gap, not
    LBNL's: it schedules with `CDL.Logical.Sources.TimeTable`, which the engine
    supports and BACTalk does not map yet. That needs a schedule kind with a module
    kernel, since Niagara schedules are calendar-based.
22. **Scenario activity.** `HeatRecoveryChillers.Enable` sat with both outputs constant
    under the shared nominal table, because both loads were zero. Its row carries a
    point inside the enable window: both loads above the chiller's minimum capacities,
    both plants on, leaving temperatures inside their limits. Every other retained
    template moves at least one output across its scenarios, except the three
    placeholders without an input, which are constant by design.

### Grading

23. **Corrected by decision 016.** The limit cycle described below was not LBNL's: the
    scalariser dropped the gains of the economizer's tuning `MultiSum`, so BACTalk's
    translation and the engine reference it produced were wrong in the same way.
    With the gains applied the economizer settles, the alternation rule is removed,
    and every output gets its end-of-scenario expectation again. The record below is
    kept as written.

    **No end-of-scenario value inside a limit cycle.** The economizer's "wet bulb rises"
    and "TChiWatRetDow hot" scenarios end with `TWsePre` and `yTunPar` alternating on
    every scan, in LBNL's reference as well. An end-of-scenario expectation on such an
    output depends only on which half of the cycle the last scan lands on. An output
    whose last four reference samples alternate therefore gets no end-of-scenario
    expectation, and D3 still judges its whole trajectory. A scan of every retained
    reference found only the economizer's four.

    **The economizer's D4 stays blocked, for a startup reason this surfaced.** The
    module `Pre` (`bactalkG36:Pre`) emits its start value for its first execution
    period after station start. CDL's `Pre`, as the engine runs it, has already
    latched its t = 0 input, so the module lags CDL by one execution period at
    startup: 1 s at the default period, and a whole scan under the scan-period policy.
    On the economizer, `pre1` sits on the enable path, and `y` is still False at 60 s
    where the reference is True. D3 passes inside the bands, but the mutation
    baseline is caught on that scan, and the row records it as its D4 blocker. Fixing
    it means the wrapper latching its input once at station start without emitting,
    in both the Java wrapper and the Shadow Runtime. That is a semantics change to
    S-LINK-2 and S-MODULE-1, left for a decision of its own.
24. **Staging up fails D3 at the 1 s module tick.** In the "stage up to 2" scenario a
    `TrueDelay` in the minimum-bypass setpoint chain lands one scan apart from the 60 s
    interpreter and reference. The scan-tick leg passes. This is the same
    discretisation class as the constant-volume fan-powered boxes, and the report says
    so.

## Consequences

Seven more chiller-plant subsystems are Tier 2 rows with engine references. All seven
pass D1 and D2, six pass D3 (stage-up at the 1 s tick is the exception), and they
catch 55–72.5 % of mutants. The economizer's D4 is blocked by the module `Pre` startup
lag (item 23). The full controller is listed with LBNL's algebraic loop.

All 38 plant templates are Tier 2b rows. The 22 that retain pass D1–D3, and
`Pumps.Primary.EnableLeadHeadered` is the first row of any tier to meet the 95 % D4
target (19 of 20). The 16 blocked rows name the class that stops each of them.

The scalariser, assembler, evaluator and grading changes are general CDL work and
apply to any future composite with arrays. All 34 earlier retained rows pass
`retain_tier2.py --check` with no drift. Nothing here is Niagara runtime
qualification. Gates G-SDK, G-WB and G-ENG remain with people.
