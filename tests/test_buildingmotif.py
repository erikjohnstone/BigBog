from bactalk.integrations.buildingmotif import BuildingMotifAdapter, BuildingMotifError


def test_buildingmotif_expands_real_g36_template() -> None:
    adapter = BuildingMotifAdapter()

    catalog = adapter.catalog("g36")
    result = adapter.instantiate(
        library="g36",
        template="vav-with-reheat",
        namespace="urn:bactalk:test#",
    )

    assert catalog["template_count"] >= 100
    assert "vav-with-reheat" in catalog["templates"]
    assert result["triple_count"] >= 15
    assert "VAV" in result["turtle"]


def test_buildingmotif_rejects_non_uri_namespace() -> None:
    adapter = BuildingMotifAdapter()

    try:
        adapter.instantiate(
            library="g36",
            template="vav-with-reheat",
            namespace="not-a-uri",
        )
    except BuildingMotifError as exc:
        assert "absolute" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("relative namespace unexpectedly accepted")
