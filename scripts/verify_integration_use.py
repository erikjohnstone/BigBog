from __future__ import annotations

import json

from bactalk.integrations.use_audit import IntegrationUseAudit


def main() -> int:
    report = IntegrationUseAudit().assert_complete()
    print(
        json.dumps(
            {
                "passed": True,
                "pinned_components": report["pinned_component_count"],
                "bound_components": report["bound_component_count"],
                "presence_only_components": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
