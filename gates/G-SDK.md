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
2. Open `niagara-module/bactalkG36/` and set `niagara_home` and `niagara_user_home`
   in `gradle.properties` to your installation (the file documents the keys).
3. Run `gradlew build` from that directory. Expected result: `bactalkG36-rt.jar` and
   `bactalkG36-wb.jar` under `build/`, with zero test failures.
4. Sign both jars per Tridium's procedure (`gradlew moduleSign` when the signing
   plugin is configured, or Workbench's module signing tool).
5. Copy the signed jars into your Workbench `modules/` directory, restart Workbench,
   and open the palette `bactalkG36`. Every block from
   `docs/niagara-lowering-matrix.md` marked `MODULE` must appear.
6. Drop one instance of each block on a wiresheet and confirm it executes (its
   `out` slot updates when inputs change).

## Evidence to return (commit under `gates/evidence/G-SDK/`)

- `build.log`: the full Gradle output.
- `bactalkG36-rt.jar.sha256` and `bactalkG36-wb.jar.sha256`.
- `palette.png`: a Workbench screenshot of the palette.
- `execution.txt`: for each block, the input values set and the output observed.
- `environment.txt`: Workbench version, JDK version, OS.

## What passing means

Only that the module builds, signs and executes. Behavioral equivalence is proven
separately by N3's kernel goldens and N7's three-way differential testing; runtime
qualification is Gate G-WB.
