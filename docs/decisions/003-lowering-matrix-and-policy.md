# 003: One lowering decision per block kind, stock first, fail closed

Status: accepted (N2). Provisional rows become final only when N7 proves them.

## Context

The native `.bog` lane (GOAL-NATIVE-BOG.md N4) needs a single answer for every
`BlockKind`: which Niagara type carries it, how exact that is, and what to do
when nothing stock fits. Today the compiler carries 32 kinds through pybog and
the remaining 26 go to generated Java ProgramObjects.

## Decision

- **The matrix is code.** `src/bactalk/niagara/lowering.py` holds one
  `LoweringDecision` per kind; `docs/niagara-lowering-matrix.md` is rendered
  from it and a stale copy fails `make test-native-bog` and CI.
- **Four classes.** `STOCK_EXACT` (28 kinds), `STOCK_WITHIN_BANDS` (9),
  `MODULE` (15), `UNSUPPORTED` (6: the `plant_*` composites, decided in N8).
- **Within-bands rows name their deviation and bounding scenarios**, and stay
  provisional until the Shadow Runtime (N6) and the three-way differential (N7)
  pass every listed scenario within tolerance:
  - `boolean_delay` → `kitControl:BooleanDelay` only when `delay_on_init` is
    true; otherwise `bactalkG36:TrueDelay` (the Tier 1 controllers set it false
    on every `TrueDelay`, which is why they need the module).
  - `one_shot` and `boolean_falling_edge` → `kitControl:OneShot` (pulse width
    versus one host tick).
  - `hysteresis` → `kitControl:Tstat` (threshold equality only).
  - `boolean_set_reset` → OneShot/Or/And/Not composite with a feedback link
    (one-cycle settle, clear priority kept).
  - `numeric_sampler` and `boolean_sample_trigger` → MultiVibrator composites
    (sample phase).
  - `pi_loop` → `kitControl:LoopPoint` (integral form, disable behaviour).
  - `boolean_assert_warning` → pass-through plus a wiresheet note (no station
    warning).
- **`pid_with_reset` is a module block.** `kitControl:LoopPoint` has no reset
  trigger and a different anti-windup form; the goal allowed it "if it holds",
  and it does not hold for the CDL contract. `bactalkG36:PIDWithReset` reuses
  the kernel already generated for ProgramObjects.
- **Policy object.** `LoweringPolicy(expert_program_objects=False)` is the
  default; `plan_lowering` returns the lane (`native_stock`,
  `native_with_module`, `program_objects`, `blocked`) and the blockers. A new
  `UNSUPPORTED` kind blocks that library item, never the pipeline.
- **Recorded now, enforced in N4.** Every run writes `niagara-lowering.json`
  beside its artifacts. The service still chooses the artifact by the
  compiler's stock table until the native emitter exists; flipping the default
  to the matrix is N4's exit condition, not N2's.

## Consequences

- Tier 1 has no `UNSUPPORTED` entry. The retained VAV reheat controller needs
  `bactalkG36:PIDWithReset`, `Pre`, `Timer`, `TrueDelay`, `TrueFalseHold` and
  `UnitDelay` (25 module blocks of 485); the multizone AHU adds
  `FirstOrderHold` and `MovingAverage` (27 of 566). That is the N3 build list;
  `BooleanInitialization`, `NumericChange`, `TimerWithReset`,
  `TimerAccumulating` and `TrimAndRespond` follow when a library item needs
  them.
- The compiler's `SLOT_NAMES` and the matrix are tested to agree until N4
  makes the matrix the only table.
