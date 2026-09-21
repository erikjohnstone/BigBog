# bactalkG36: BACTalk's Guideline 36 kernel blocks for Niagara 4

The `MODULE` rows of `docs/niagara-lowering-matrix.md`: the CDL and Guideline 36
blocks that no stock `kitControl` component reproduces. Each component wraps one
plain-Java kernel from `bactalkG36-rt/src/com/bactalk/g36/kernel/`; the kernels
have no Niagara dependency and are the same code the ProgramObject generator used
to emit, now parameterised at construction instead of baked in as constants.

| Component | Kernel | Contract |
|---|---|---|
| `bactalkG36:TrueDelay` | `TrueDelay` | `CDL.Logical.TrueDelay` (honours `delayOnInit`) |
| `bactalkG36:Timer` | `Timer` | `CDL.Logical.Timer` |
| `bactalkG36:TimerWithReset` | `TimerWithReset` | `Buildings.Templates.Plants.Controls.Utilities.TimerWithReset` |
| `bactalkG36:TimerAccumulating` | `TimerAccumulating` | `CDL.Logical.TimerAccumulating` |
| `bactalkG36:TrueFalseHold` | `TrueFalseHold` | `CDL.Logical.TrueFalseHold` |
| `bactalkG36:Pre` | `Pre` | `CDL.Logical.Pre`, `host_tick_v1` profile |
| `bactalkG36:UnitDelay` | `UnitDelay` | `CDL.Discrete.UnitDelay` |
| `bactalkG36:FirstOrderHold` | `FirstOrderHold` | `CDL.Discrete.FirstOrderHold` |
| `bactalkG36:MovingAverage` | `MovingAverage` | `CDL.Reals.MovingAverage` |
| `bactalkG36:PIDWithReset` | `PidWithReset` | `CDL.Reals.PIDWithReset` |
| `bactalkG36:TrimAndRespond` | `TrimAndRespond` | `G36.Generic.TrimAndRespond` (`have_hol` via `holdEnabled`) |
| `bactalkG36:BooleanInitialization` | `BooleanInitialization` | `Buildings.Templates.Plants.Controls.Utilities.Initialization` |
| `bactalkG36:NumericChange` | `NumericChange` | change / increase / decrease detector |

## What CI proves

`tests/test_native_bog_kernels.py` (tier `native_bog`, needs `javac`):

- the kernels compile and reproduce the Open Control Engine golden traces and
  BACTalk's IR interpreter on randomised input sequences (`KernelHarness`);
- the component wrappers compile against `niagara-module/stubs` (a minimal
  `javax.baja` surface: `BComponent`, slots, status values, clock);
- `module-include.xml`, the wrappers' slots and `src/bactalk/niagara/module.py`
  agree.

## What CI cannot prove

Building, signing and running the module needs the Niagara SDK and a signing
certificate. That is **Gate G-SDK** (`gates/G-SDK.md`): set `niagara_home` in
`gradle.properties`, run `./gradlew build`, sign, install, and return the
evidence the gate lists. Nothing in this directory claims runtime qualification.

## Layout

```
bactalkG36/
  settings.gradle.kts  build.gradle.kts  gradle.properties  niagara-module.xml
  bactalkG36-rt/       runtime part: kernels, components, module-include.xml, lexicon
  bactalkG36-wb/       Workbench part: palette
../stubs/              javax.baja stubs for CI compilation only
```
