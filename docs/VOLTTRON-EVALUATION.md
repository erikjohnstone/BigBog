# VOLTTRON evaluation and adoption decision

Verified 2026-09-19 against the modular Eclipse repositories and published
release-candidate packages.

## Decision

Adopt VOLTTRON as an optional Linux edge/lab data plane. Do not make it the
Niagara authoring compiler, the safety authority, or a core application
dependency.

This gives BACTalk a common Python/message-bus boundary for BACnet, fake devices,
historian data, and future vendor connectors while the typed control IR remains
the source of truth for generation and verification. Niagara output still goes
through pybog, simulation, artifact hashing, named human approval, and manual
Workbench import.

## What is immediately useful

- The Platform Driver normalizes device points onto publish/subscribe topics.
- The BACnet driver now uses `bacpypes3` through the protocol-proxy packages.
- The fake driver can support fast agent and message-bus tests on Linux.
- Agent lifecycle, configuration store, authentication/capabilities, historians,
  and topic watchers are useful edge infrastructure.
- Device registries provide a stable handoff from BACTalk's point model into the
  runtime. BACTalk now generates these as approval-hashed, read-only artifacts.

## Release audit findings

The current `volttron==11.0.0rc3` wrapper resolves to a fragmented set of alpha
and release-candidate packages, including `volttron-core==2.0.0rc34`. It is not
a stable production dependency today.

The stack installed successfully in an isolated Python 3.11 environment. A
contract check loaded a generated BACTalk registry through the actual
`BacnetPointConfig` model from `volttron-lib-bacnet-driver==2.0.0rc3` and loaded
the generated device config through `BacnetRemoteConfig`. All three points were
accepted and remained read-only.

The same install failed on Python 3.14 while building the stack's pinned
`gevent==24.2.1`. First boot also requires Poetry even though it is not declared
by the wrapper as a runtime dependency. On macOS, first boot reached the ZeroMQ
router and failed because current router code hard-codes a Linux abstract IPC
address (`ipc://@...`) and ignores the parsed `local_address` option. Linux is
therefore the only supported BACTalk edge target for this pin.

## Safety findings

The old `volttron-actuator` repository is archived and its README says it may
contain unpatched vulnerabilities and must not be used in production. It cannot
be the AI safety boundary.

The current `bacnet-scan-tool` is promising but pre-stable. Its API includes
scan, read, and write-property routes without an application authentication
layer in the repository version reviewed. It also depends on a personal GitHub
fork/branch. Do not ship it unchanged.

BACTalk's edge profile instead uses defense in depth:

1. Generated registries force `Writable=FALSE` for all points.
2. Generated agents receive no command capability.
3. VOLTTRON is network- and process-isolated from the compiler/review service.
4. Any future command request passes a separately owned policy gateway with
   allowlisted points, engineering bounds, rate-of-change limits, leases,
   schedules, stale-data checks, emergency revocation, and audit logging.
5. Live enablement requires a separate site-specific commissioning ceremony;
   approving a programming artifact never enables control.

## ACE IoT connector audit

ACE IoT documents a field-tested Desigo-to-VOLTTRON integration used to collect
data from legacy Siemens P2 controllers. That validates the architectural
direction. However, the public ACE organization currently exposes only a small
`desigo-credential-handler` repository for this path, and that repository has no
declared license. No commercially cleared public Desigo API driver or
Niagara-to-VOLTTRON connector source was found in the organization during this
review. Those are partnership/licensing leads, not dependencies we can ship.

## Near-term integration sequence

1. Run the pinned stack in a Linux container/VM and prove platform plus fake
   driver startup.
2. Load BACTalk-generated read-only configs and confirm normalized topic output.
3. Attach the same topic contract to a BOPTEST BACnet test case.
4. Add a telemetry-only BACTalk agent that records observations and test
   assertions; no write capability.
5. Build an independent policy gateway before evaluating any laboratory write
   path.
6. Request explicit licenses/source access from ACE for Desigo and Niagara
   connectors and security-review them before adoption.

## Pinned components

Exact package pins live in `ops/volttron/requirements.txt`; upstream revisions
are recorded in `ops/stack.lock.json`. Preserve Apache-2.0 notices for Eclipse
VOLTTRON components and re-run the transitive-license and vulnerability review
for every pin change.
