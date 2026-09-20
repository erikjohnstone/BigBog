from __future__ import annotations

import json

from bactalk.integrations.buildingmotif import BuildingMotifAdapter, BuildingMotifError


def main() -> int:
    adapter = BuildingMotifAdapter()
    catalog = adapter.catalog("g36")
    assert catalog["template_count"] >= 100
    assert "vav-with-reheat" in catalog["templates"]
    expanded = adapter.instantiate(
        library="g36",
        template="vav-with-reheat",
        namespace="urn:bactalk:contract#",
    )
    assert expanded["triple_count"] >= 15
    assert "VAV" in expanded["turtle"]
    rejected = False
    try:
        adapter.catalog("../../etc")
    except BuildingMotifError:
        rejected = True
    assert rejected
    print(
        json.dumps(
            {
                "engine": "BuildingMOTIF",
                "version": "0.4.0",
                "g36_templates": catalog["template_count"],
                "expanded_template": expanded["template"],
                "expanded_triples": expanded["triple_count"],
                "unknown_library_rejected": rejected,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
