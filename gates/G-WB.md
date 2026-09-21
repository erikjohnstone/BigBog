# Gate G-WB: calibrate the Shadow Runtime against a licensed Workbench

Status: `WAITING_ON_HUMAN`

## Why a human is needed

The Niagara Shadow Runtime (milestone N6) is a model of how Niagara executes a
`.bog`. Every behavior it assumes is listed in `docs/niagara-semantics.md` with a
source. Assumptions marked `ASSUMED` can only be confirmed by running the same file in
a real Niagara station, which needs a licensed Workbench. Until this gate passes,
every result the Shadow Runtime produces is labelled `bog-simulated`, below
`runtime-qualified`.

## What you need

- A licensed Niagara 4 Workbench with a localhost station (a JACE or Edge device is
  better but not required for the first pass).
- The signed `bactalkG36` module from Gate G-SDK installed in that Workbench.
- About two hours.

## Steps

1. Check out the repository at the commit named in `STATUS.md` under N7.
2. Open `calibration/README.md`. It lists one `.bog` per assumption, in the order to
   run them, and for each one the exact input sequence to apply and the histories to
   export.
3. For each calibration file: import it into the station, apply the inputs as
   described (they are writable points inside the file; set them at the listed
   times), let the listed histories fill, then export each history as CSV into
   `gates/evidence/G-WB/<assumption-id>/`.
4. Run `python scripts/calibrate_shadow_runtime.py gates/evidence/G-WB`. It compares
   the exported histories with the Shadow Runtime's expected traces and rewrites the
   status of each assumption in `docs/niagara-semantics.md` to `VERIFIED` or
   `CONTRADICTED`, and prints a summary.
5. Import each Tier 1 exported `.bog` (listed in `calibration/README.md`) into the
   station and confirm it opens with no errors in the Workbench console, that every
   folder renders, and that no link is broken. Record the outcome in
   `gates/evidence/G-WB/imports.md`.

## Evidence to return

- The exported history CSVs, one directory per assumption.
- `imports.md` with the Workbench version and any console messages.
- The updated `docs/niagara-semantics.md` (the script edits it) in the same commit.

## What passing means

Every assumption reads `VERIFIED`, or every `CONTRADICTED` assumption has a failing
test opened against the Shadow Runtime and a fix committed before the next release.
Passing this gate moves evidence produced by the Shadow Runtime from `bog-simulated`
toward `runtime-qualified`. It still does not mean field qualification; that is a
commissioning activity on the actual equipment.
