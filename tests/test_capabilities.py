from bactalk.capabilities import CapabilityRegistry
from bactalk.demo import generalist_demo_job


def test_capability_registry_is_truthful_and_matches_installed_ahu_pack() -> None:
    registry = CapabilityRegistry()
    inventory = registry.inventory()

    assert inventory["production_ready"] is False
    assert inventory["summary"]["production_supported_packs"] == 0
    assert inventory["summary"]["catalogued_equipment_families"] >= 15
    assert registry.match_job(generalist_demo_job()).id == "ahu-safety-cooling-v1"
    vav = registry.get("g36-vav-reheat-mvp")
    assert vav.artifact_coverage.logic is True
    assert vav.artifact_coverage.histories is True
    assert vav.artifact_coverage.graphics is False
    assert vav.verification_coverage.niagara_runtime is False
    release = registry.release_assessment(vav.id)
    assert release["eligible_for_production_support"] is False
    assert "artifact.graphics" in release["blocking_gate_ids"]
    assert "verification.dynamic_building" in release["blocking_gate_ids"]
    assert "verification.niagara_runtime" in release["blocking_gate_ids"]
    assert "verification.field_qualified" in release["blocking_gate_ids"]
    assert release["passed_gates"] < release["total_gates"]


def test_every_catalogued_family_exposes_its_blocker() -> None:
    families = CapabilityRegistry().inventory()["families"]

    assert all(item["blocker"] for item in families)
