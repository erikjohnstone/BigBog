# 012: Tier 4 standard sequences: configurable, not forked (N10)

Status: accepted (N10). Builds on decision 011.

## Context

Tier 4 is the common non-G36 equipment: rooftop units, heat pumps, dedicated
outdoor air units, exhaust fans, standalone pumps. GOAL-NATIVE-BOG.md asks for a
BACTalk sequence document per type in the style of Guideline 36 with cited sources,
Gate G-ENG before implementation, one implementation per type that declared options
configure, and the label "BACTalk standard sequence (engineer-approved requirements)",
never "G36".

## Decisions

1. **A catalogue of items and configurations.** `bactalk.protocol.catalog` holds
   every protocol item (Tier 3 and 4 today): one graph builder per equipment type and
   one or more configurations, each a declared option set. A configuration is the unit
   of everything downstream: its own retained requirement set
   (`requirements-<config>.json`), its own adequacy artifact, its own coverage row,
   its own Gate G-ENG digest, its own entry in `/api/protocol/sequences`.

2. **Options resolve into the requirements, not into forks of the logic.** The
   requirement sets are written by one author module per item
   (`<item>/author.py`, checked against the committed JSON by a test) that takes the
   option and emits the requirements that apply, in plain language with the option's
   numbers in the text. The graph builder takes the same option and adds or omits the
   block groups it implies (an isolation damper interlock, an economizer, auxiliary
   heat, an energy recovery wheel). There is one builder per type; a test checks that
   every requirement of every configuration is implemented by a traced block and
   tested by a generated scenario.

3. **Sources are designer practice and say so.** Every Tier 4 citation names the
   BACTalk sequence document for the type with `fidelity: designer`; a test refuses
   any Tier 4 requirement whose citation names Guideline 36 and any title that does.
   The sequence family is `BACTALK_STANDARD_SEQUENCE` and the label the protocol
   attaches to the job (`sequence.parameters.protocol.label`) is the required
   wording.

4. **Setpoints are inputs; staging requirements are stated at the nominal
   setpoints.** A rooftop unit compares the zone with the live setpoint; the
   requirement states the threshold as a number at the nominal setpoint so the test
   author can drive both sides of it, and says so in its text.

5. **The first five items.** Exhaust fan (basic, isolation damper), duty/standby pump
   pair, packaged rooftop unit (with and without economizer), air-source heat pump
   (with and without auxiliary heat), dedicated outdoor air system (with and without
   energy recovery): nine configurations, each graded D1–D4 by the same adequacy
   script as Tier 3, with a 100-mutant sample recorded as such.

## Consequences

- Adding a Tier 4 type is an author module, a graph builder and a registration;
  nothing in the protocol, the API, the coverage report or the web page changes.
- Gate G-ENG is per configuration: an engineer approves the exact digest of the
  requirement set they read, options resolved.
- The N0 exhaust fan and pump packs (`bactalk.sequences`) stay in the repository for
  the demo project's topology; the Tier 4 items are their protocol-grade
  replacements and are what the coverage report grades.
