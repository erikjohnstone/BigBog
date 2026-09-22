# 013: Tier 5 custom, job-specific sequences (N11)

Status: accepted (N11). Builds on decisions 011 and 012.

## Context

A contractor's specification often carries sequences no library has. GOAL-NATIVE-BOG.md
N11 asks that the contractor upload the spec section, that the AI draft a typed IR
program citing the spec text per block group, that the tests follow the protocol from
the contractor's description and the spec paragraphs with the contractor approving the
requirements list, that the program pass its scenarios in the interpreter and the
Shadow Runtime and mutation testing, that it appear in the approval digest labelled
"custom, job-specific", and that it compose with library equipment in one `.bog`
through declared typed signals only.

## Decisions

1. **Two AI roles, two drafts, one gate between them.** `bactalk.protocol.custom`
   drafts the requirement set from the spec section with the conversation-role
   provider (`draft_requirements`: the model returns the set as JSON text; BACTalk's
   `RequirementSet` validator is authoritative and pins the sequence id and tier) and
   the program with the coding-role provider (`draft_program`: the model returns a
   graph; BACTalk checks every declared point has its block and every requirement is
   traced by at least one block). The program is drafted only after the contractor
   approved the requirement digest (`POST /api/protocol/custom/{id}/program` answers
   409 before that): the logic author sees approved requirements, never the spec's
   loose ends. The requirement drafter and the logic author are different providers by
   configuration (`CEREBRAS_CHAT_MODEL`, `CEREBRAS_CODING_MODEL`), which is the
   protocol's "different models where available".

2. **Every requirement cites its paragraph.** The drafter is told to cite
   `citation.section` / `citation.paragraph` with `verbatim` or `paraphrase` fidelity
   and never to invent a source; the fixture test refuses a custom requirement with no
   paragraph. The program's `metadata.traceability` (block → requirement) and
   `metadata.citations` (requirement → paragraph) make "citing the spec text per
   block group" a lookup, not a comment.

3. **Unstated behaviour stays a question.** The drafter returns `questions` and
   `assumptions` beside the set; they are retained on the record and shown with the
   set. The test author's own gaps (unstated failure behaviour) join them. Nothing is
   resolved silently.

4. **The same protocol, the same gate, one more label.** A custom record is a
   protocol sequence to the API (`/api/protocol/sequences` lists it beside the
   library rows), to the approval route (the contractor is the reviewer of record),
   to the adequacy check (`POST /api/protocol/custom/{id}/adequacy`, mutants
   optional) and to `WorkbenchService`: the run carries
   `sequence.parameters.protocol.label = "custom, job-specific"`, family
   `CUSTOM_JOB_SPECIFIC`, the spec's sha256, and cannot be approved or exported before
   its requirement digest is.

5. **Composition through typed signals only.** The fixture
   (`tests/test_native_bog_tier5.py`) composes the LBNL AHU and VAV box (Tier 1) with
   two custom sequences (`bactalk.library_tier5_fixture`: a kitchen hood / makeup air
   interlock reading the AHU's supply fan status, and a seasonal changeover whose
   heating-season output feeds the VAV's hot water plant status) through
   `ProjectSignalBinding` records, runs the project suite, and assembles one station
   `.bog` that lowers natively and validates. The assembler now finds boundary points
   under the native emitter's Inputs/Outputs folders as well as as direct children
   (the legacy layout).

6. **Fixtures are retained as catalogue rows; real custom sequences are not.** The
   two fixture sequences are registered as Tier 5 rows labelled "custom, job-specific
   (fixture)" so the coverage report and the adequacy script grade them like any row.
   A contractor's custom sequence lives with its job in `custom-sequences/` under the
   runs root and is graded on demand.

7. **Promotion is a copy, not a link.** A custom sequence reused across jobs becomes
   a Tier 4 item by the N10 route: an author module, a builder and a registration
   (decision 012). Nothing in the record points at the library.

## Consequences

- Without an AI provider the draft routes answer 503; with one whose output fails
  BACTalk's validation they answer 502 with the reason. A fake provider proves the
  path in `tests/test_protocol_custom.py`.
- Mutation catch rates on the small custom programs sit below the 95 % target, as
  they do on Tier 4; the survivors are the same equivalent classes (priority level and
  facet mutations on writable points, input defaults the scenarios always override)
  and are reported as measured (decision 012's coverage note).
