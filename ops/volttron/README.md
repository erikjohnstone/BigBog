# VOLTTRON edge-lab profile

VOLTTRON is an optional, isolated data-plane sidecar. It is not linked into the
BACTalk compiler, it is not an approval authority, and it is not allowed to
write to a live building in this profile.

## Reproducible environment

Use a Linux host or container and Python 3.11. The current modular release
candidate does not install on Python 3.14 because its pinned `gevent==24.2.1`
cannot build there. Its ZeroMQ router also hard-codes Linux abstract IPC syntax,
so the current package does not boot natively on macOS.

```bash
python3.11 -m venv .volttron-venv
.volttron-venv/bin/pip install -r ops/volttron/requirements.txt
```

`poetry` is pinned explicitly because `volttron-core` invokes it during first
boot but its wrapper package does not declare it as a runtime dependency.

## Safety profile

- Run on an OT-isolated Linux host/container with a dedicated unprivileged user.
- Bind management traffic to a private interface and firewall BACnet UDP/47808.
- Do not install `volttron-actuator`; its upstream repository is archived and
  explicitly says it must not be used in production.
- Do not deploy `bacnet-scan-tool` unchanged. Its current API includes an
  unauthenticated write endpoint.
- Load only BACTalk-generated registry files. They force every point's
  `Writable` value to `FALSE`, even when the source scan reports a writable
  BACnet object.
- Treat generated device configs as review artifacts. Approval never changes
  their read-only posture and never connects to a network.

For a job with a BACnet scan, the run directory contains `volttron/manifest.json`,
one Platform Driver device JSON per mapped device, and one registry CSV per
device. Run the contract check inside the edge environment:

```bash
PYTHONPATH=src .volttron-venv/bin/python scripts/verify_volttron_contract.py
```

See `docs/VOLTTRON-EVALUATION.md` for the adoption decision and known upstream
risks.
