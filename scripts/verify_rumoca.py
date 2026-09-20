from __future__ import annotations

from bactalk.integrations.rumoca import RumocaCompiler, RumocaError


def main() -> None:
    compiler = RumocaCompiler()
    result = compiler.flatten_g36(
        "AHUs.MultiZone.VAV.SetPoints.SupplySignals",
        timeout=180.0,
    )
    assert result["schema"] == "bactalk.rumoca-flatten/v1"
    assert result["variable_count"] >= 100
    assert result["equation_count"] >= 50
    assert result["top_level_input_count"] == 3
    assert len(result["flat_ir_sha256"]) == 64
    assert result["provenance"]["rumoca_revision"] != "unavailable"
    assert result["provenance"]["modelica_buildings_revision"] != "unavailable"

    # Keep the current composite-model boundary executable and explicit. This
    # changes from an expected rejection to a success assertion when Rumoca can
    # instantiate parameter-derived conditional blocks in the full controller.
    try:
        compiler.flatten_g36(
            "AHUs.MultiZone.VAV.Controller",
            parameters={
                "eneStd": (
                    "Buildings.Controls.OBC.ASHRAE.G36.Types.EnergyStandard."
                    "ASHRAE90_1"
                ),
                "venStd": (
                    "Buildings.Controls.OBC.ASHRAE.G36.Types.VentilationStandard."
                    "ASHRAE62_1"
                ),
            },
            timeout=180.0,
        )
    except RumocaError as exc:
        assert "conditional component `lesHys` requires parameter expression" in str(exc)
    else:
        raise AssertionError(
            "full VAV controller now flattens; promote it into the production lowering path"
        )

    print(
        "Rumoca contract: OK "
        f"({result['variable_count']} variables, {result['equation_count']} equations; "
        "full VAV conditional-elaboration blocker retained as evidence)"
    )


if __name__ == "__main__":
    main()
