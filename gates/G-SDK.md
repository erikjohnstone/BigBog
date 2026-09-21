# Gate G-SDK: build and sign the `bactalkG36` Niagara module

Status: `WAITING_ON_HUMAN`

## Why a human is needed

Compiling a Niagara 4 module requires the Niagara SDK (`niagara-sdk`, the `nre`
runtime and the Gradle plugins shipped with Workbench) and a code-signing
certificate registered with Tridium. Neither is redistributable, so CI compiles the
module's computational kernels against stub interfaces only (milestone N3). The real
module has never been built until this gate passes.

## What you need

- A licensed Niagara 4 Workbench installation with the SDK (4.13 or newer).
- A code-signing certificate accepted by that Workbench (see Tridium's "Niagara
  Developer Guide", module signing).
- JDK matching the Workbench release (Tridium documents the version per release).

## Steps

1. Check out the repository at the commit named in `STATUS.md` under N3.
2. In `niagara-module/bactalkG36/gradle.properties` set `niagara_home` (and
   `niagara_user_home`) to your installation. If the Gradle plugins are not under
   `niagara_home/etc/m2/repository`, set `gradlePluginHome` too.
3. Put your signing profile outside version control and point
   `bactalkSigningProfile` and `bactalkSigningAlias` at it (see `build.gradle.kts`;
   the build refuses the default profile on purpose).
4. From `niagara-module/bactalkG36/` run `./gradlew build` (Windows:
   `gradlew.bat build`). Expected: `bactalkG36-rt/build/libs/bactalkG36-rt.jar`
   and `bactalkG36-wb/build/libs/bactalkG36-wb.jar`, signed, with zero test
   failures. The sources compile in CI against `niagara-module/stubs`; any error
   the real SDK raises that the stubs did not is a finding to record.
5. Copy both jars into Workbench's `modules/` directory, restart Workbench and open
   the `bactalkG36` palette. The three folders (Timing, Discrete, Loops) and all 13
   components in `bactalkG36-rt/module-include.xml` must appear.
6. Drop one instance of each component on a wiresheet, set its parameters, drive
   its inputs and confirm the outputs update: `TrueDelay` with `delayTime` 10 s
   and `delayOnInit` false must pass an initially true input through at once;
   `Timer` must count while `in` is true; `PIDWithReset` must move `out` when
   `measurement` departs from `setpoint`. Set an input to null and confirm the
   outputs go null and return to ok when the input is valid again.

## Evidence to return (commit under `gates/evidence/G-SDK/`)

- `build.log`: the full Gradle output.
- `bactalkG36-rt.jar.sha256` and `bactalkG36-wb.jar.sha256`.
- `palette.png`: a Workbench screenshot of the palette.
- `execution.txt`: for each component, the parameters set, the input values
  applied and the outputs observed, including the null-status check.
- `environment.txt`: Workbench version, JDK version, OS, Gradle plugin version.
- `findings.md`: anything the SDK rejected that the CI stubs accepted, with the
  compiler message verbatim (empty file if nothing).

## What passing means

Only that the module builds, signs and executes. Behavioral equivalence is proven
separately by N3's kernel goldens and N7's three-way differential testing; runtime
qualification is Gate G-WB.
