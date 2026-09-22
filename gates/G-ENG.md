# Gate G-ENG: requirements approval (Tiers 3, 4 and 5)

**Status: WAITING_ON_HUMAN.** Nothing in this repository can pass this gate; a qualified
controls engineer does, once per requirement set digest.

## What the gate protects

Tiers 3–5 have no LBNL reference model. The requirement set
(`bactalk.protocol.requirements`, one JSON document per sequence and configuration, for
example `src/bactalk/library_tier3/hw_plant_boiler/requirements.json` or
`src/bactalk/library_tier4/rtu/requirements-economizer.json`; for a Tier 5 custom
sequence the record under `custom-sequences/`) is the only statement of what
"correct" means: the logic author implements it, the test author generates every
scenario from it, and the adequacy report proves the suite against the logic. If the
requirements are wrong, everything downstream is consistently wrong. So a human decides.

Until the exact digest of a requirement set is approved:

- `GET /api/protocol/sequences/{id}` reports `gate_g_eng: unapproved` (or `stale` when an
  earlier digest was approved and the set changed since);
- a candidate built from it (`sequence.parameters.protocol.requirements_digest`) cannot be
  approved or exported: `POST /api/runs/{id}/approve` and every export answer 409 with the
  gate named;
- `docs/coverage.md` lists the item with the gate status beside D1–D4.

Who approves: a qualified controls engineer for Tier 3 (G36 text) and Tier 4 (BACTalk
standard sequences, one approval per configuration); the contractor for a Tier 5
custom sequence drafted from their own specification (the program is drafted only after
that approval).

## What the engineer does

1. Open the sequence in the web app (Libraries → Requirements) or read
   `docs/test-plans/<id>.md`. Every requirement carries its citation and its fidelity
   (`verbatim`, `paraphrase`, `designer`); every designer default is a parameter named in
   the text.
2. Read the questions the protocol raised (ambiguous requirements, unstated failure
   behaviour). Each one is a place where the requirements do not decide; answer it by
   editing the requirement set, which changes the digest, or accept it as out of scope.
3. Approve the exact digest: `POST /api/protocol/sequences/{id}/approve` with
   `{"reviewer": "<name>", "requirements_digest": "<digest>", "note": "..."}` (the web
   app does this). The approval is retained under `requirement-approvals/` and is bound
   to that digest; a later change to the requirements needs a new approval.

## What the gate does not claim

Approval says the requirements are what the engineer wants built. It does not say the
logic is correct (the adequacy report and D1–D4 say that, as measured), and it is not
Niagara runtime qualification (Gates G-SDK and G-WB).
