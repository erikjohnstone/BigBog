# Library authoring: implementing a sequence in the typed IR (Tier 3 and up)

Tiers 1 and 2 translate LBNL's CDL. From Tier 3 on there is no reference model:
an engineer (human or agent) implements the sequence in BACTalk's typed IR directly
from the Guideline 36 text, and the Test Generation Protocol (GOAL-NATIVE-BOG.md)
proves it. This page is the authoring contract; `docs/decisions/003` and
`docs/niagara-lowering-matrix.md` say what the IR lowers to.

## What you write

A `JobSpec` with a `ControlGraph` (`bactalk.domain`): blocks, links and boundary
points. Every block names the requirement ids it implements in the graph's
`metadata.traceability` (block id → `["R-03", "R-04"]`); the citation itself lives
in the requirement set. `tests/test_native_bog_tier3.py` checks that every block is
traced and every requirement is implemented; a block with no requirement is a
finding. `bactalk.library_tier3.hw_plant_boiler.graph` is the worked example.

- **Points** (`PointSpec`): one per public input and output, SI units as the
  guideline states them (K, Pa, m3/s, ppm). Inputs are `sensor`, `setpoint` or
  `status`; outputs `command` or `alarm`. Integer signals (requests, modes, stages)
  are numeric points; the `Round` kernel exists for the few places CDL rounds.
- **Blocks**: only kinds in `BlockKind` (58 plus `numeric_round`). Use the same
  idioms LBNL uses so the lowering matrix stays exact: `pid_with_reset` for loops
  (`pi_loop` cannot take a linked `direct` input, decision 011),
  `trim_and_respond` for reset requests, `boolean_delay`/`timer` for persistence,
  `hysteresis` for deadbands, `one_shot`/`boolean_falling_edge` for edges,
  `numeric_switch`/`boolean_switch` for mode selection. Do not encode timing in
  constants that a scan rate would change; timing lives in the timed blocks.
- **Links**: typed; the graph validator refuses a boolean into a numeric slot and
  an unlinked required input.
- **Parameters** that the guideline leaves to the designer (design airflows,
  setpoint limits, delays) are `numeric_const` blocks with a `description` naming
  the parameter and its default, so the parameter schema and the intake form can
  expose them.

## What you must not write

- Tests. The logic author never writes or edits acceptance tests; the protocol's
  test author does, from the approved requirements alone, and the worker that runs
  it has no access to the graph. A logic author who needs a test changed raises a
  question.
- Equipment-specific code in the compiler, emitter or Shadow Runtime. If a block is
  missing, add it to the matrix, the module and the runtime with its own row and
  kernel (decision 003); the fan coil's `Limiter` and `Round` in N8 are the pattern.

## How it is proven

The item is done when `docs/coverage.md` lists it with:

1. D1 native by default: `plan_lowering` returns `native_stock` or
   `native_with_module`, no blockers.
2. D2 statically valid: the emitted `.bog` passes the validator with no error.
3. D3: the Shadow Runtime and the interpreter agree inside the bands
   (decision 008) on every scenario. With no reference model the third leg is the
   requirement-traced suite; a failing scenario names its requirement.
4. D4: a seeded mutant sample is caught at or above 95 %, every decision branch is
   exercised (the report's decision coverage), and every invariant held across at
   least 10 000 randomised input sequences.

Anything below that is listed with its exact blocker, never rounded up.

## Where an item lives

`bactalk.protocol.catalog` registers every item: a graph builder, one or more
configurations (declared options, decision 012), the retained requirement set and
adequacy artifact per configuration. Tier 3 items sit in `bactalk.library_tier3`, Tier 4
(BACTalk standard sequences, never labelled G36) in `bactalk.library_tier4`, the Tier 5
composition fixtures in `bactalk.library_tier5_fixture`. Each item has an `author.py`
that writes its requirement JSON (`--check` verifies the committed file), a `graph.py`
with the builder, and a registration in the package's `__init__`. Adding a type is
those three things; the API, the coverage report and the web page pick it up.

## Workflow

1. Draft the requirements (`bactalk.protocol.requirements`, one JSON document per
   sequence): numbered, plain language, each with inputs, conditions, timing,
   expected outputs, alarms, failure behaviour and recovery, and a citation. A human
   approves the set in the web app (Libraries → Requirements, Gate G-ENG); the
   approval is bound to the set's digest.
2. Implement the graph from the approved requirements (this page).
3. Run the test author against the same approved set; it never sees step 2.
4. Run the adequacy check (`scripts/protocol_adequacy.py <item>`, retained as
   `adequacy.json` beside the requirements and `docs/test-plans/<item>.md`); take the
   survivors and failed invariants back to step 3, or raise the requirement as
   ambiguous.
5. A failure that neither side can resolve is classified (logic bug, test bug,
   ambiguous requirement) and only the last becomes a question for a human.
6. The readable test plan (requirement → scenarios → expected → pass/fail, with the
   mutation and invariant results) joins the approval digest and is the
   commissioning functional test plan.
