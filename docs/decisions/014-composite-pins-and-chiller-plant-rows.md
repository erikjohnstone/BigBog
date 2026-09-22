# 014: Composite pins, the last four Tier 2 blockers and the first chiller-plant rows

Status: accepted (N8 follow-up). Builds on decisions 001 and 010.

## Context

N8 left four Tier 2 configurations blocked. The single-zone AHU (ASHRAE and Title 24)
and the fan coil stopped in the translation pipeline. The cooling-only Title 24 box
stopped at the engine. N8 step 1, pinning a Modelica Buildings commit that carries
`G36/Plants/Chillers`, had not started. This record covers what unblocked the four rows,
what the plant rows needed, and where the full chiller-plant controller still stops.

## Decisions

1. **An opaque child composite's ports are pins.** A block whose internals are not in the
   graph is opaque. Its typed ports are the boundary of that child: an `Input` is a sink
   and an `Output` a source, the reverse of the same port on the composite being
   normalised. Connection sets that mix such pins with ports of unknown direction are
   resolved by single assignment. With exactly one known source, the unknown members
   are sinks. With no known source and exactly one unknown member, that member is the
   source. Anything else stays an error. This fixed the fan coil, whose child-first
   `connect` had classified a pin as a boundary source
   (`bactalk.integrations.cxf_connections`).
2. **An edge that leaves a composite passes through scalarisation.** When the array
   scalariser meets a scalar port wired to a target outside the composite, it keeps the
   edge and re-attaches it after rebuilding the composite's own edges. An array port
   wired outside its composite is still refused with the port and target named
   (`cxf_arrays`).
3. **Icon-only `extends` is dropped.** A composite that extends only `...Icons.*` classes
   carries no behaviour through the base. The assembler removes the clause, and the
   report counts it as `icon_only_extends_removed`. Any other base still blocks.
4. **Declared absent inputs.** A parameter set can remove a conditional input from the
   engine's instance while the translated interface keeps it, as `TDis` on the Title 24
   cooling-only box does. `G36Library.execute` takes `absent_inputs`. The names must be
   public inputs, and they count as supplied for the first-sample check. The retained
   reference records them, and every reference now carries the key, empty when none.
5. **Three more CDL classes in the importer.** `Reals.Average` and `Integers.LessEqual`
   map to existing kinds. `Reals.LimitSlewRate` becomes `numeric_limit_slew_rate`,
   discretised as the Open Control Engine does it: the first tick passes `u` through,
   later ticks lag `u` by `Td` (implicit Euler) and clamp the change to
   `fallingSlewRate·dt … raisingSlewRate·dt`. kitControl's `Ramp` is a signal generator,
   so the kind lowers to a new `bactalkG36:LimitSlewRate` module kernel. Java and Python
   ports agree on the equivalence rows.
6. **A second, locked Modelica Buildings checkout for plants.** `modelica-buildings-plants`
   in `ops/stack.lock.json` pins LBNL master `a3cfdde` as a sparse checkout of
   `Controls/OBC` and `Utilities`. It is used only by configurations whose `source` is
   `plants`. The tagged release keeps translating every airside row, so no retained
   airside translation moved.
7. **modelica-json: component-array element connects.** LBNL's plant CDL writes
   `connect(halRes[1].y, …)`. modelica-json looked for an instance named `halRes[1]` and
   failed. The locked patch rewrites `name[i].port` to `name.port[i]` unless `name[i]`
   is itself an instance. The patch digest in the lock is updated.
8. **Plant rows carry their own operating point and loop tuning.** The shared nominal
   table suits airside controllers. With it, every plant scenario sat disabled: the plant
   was unscheduled with no requests, and the bypass pump was off. A configuration can
   now override its nominal inputs. Two perturbation rules were added. A request count
   carried as a Real moves to zero and to double. A speed ratio moves to half and to
   full. No existing row has such an input. The head-pressure and bypass loops ship
   LBNL's 0.5 s integral time. At Tier 2's 60 s scan, explicit integration flips those
   outputs between their limits on every scan. The rows set a 120 s integral time and
   say so in their description. A scan of every retained reference found no other
   output flipping this way.

## What remains blocked

The full `Plants.Chillers.Controller` and its staging, pump, tower and economizer
subsystems still stop at arrays that cross composite boundaries.

| Subsystem | Where it stops |
|---|---|
| Economizers | more than one source in a folded connection set |
| Pumps.ChilledWater | `controllerType` is left ungrounded |
| Pumps.CondenserWater | `mulOr` folds are left undriven |
| Towers | an array port is wired outside its composite |
| Staging.SetpointController | 293 undriven ports |
| Staging.Processes.Up and Down | 482 and 528 undriven ports |

The fix is to scalarise opaque child array ports per index, with inferred directions,
and to emit per-index external edges for array sources. That is follow-up work.

## Consequences

Every LBNL G36 airside, zone and terminal-unit controller now retains with an Open
Control Engine reference. The plant rows prove the second checkout, the translator patch
and the importer on five chiller-plant sequences. None of this is Niagara runtime
qualification. Gates G-SDK, G-WB and G-ENG remain with people.
