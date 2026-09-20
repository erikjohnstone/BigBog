from __future__ import annotations

import pytest

from bactalk.integrations.rumoca import RumocaCompiler


def test_rumoca_wrapper_rejects_parameter_injection() -> None:
    with pytest.raises(ValueError, match="invalid Modelica parameter name"):
        RumocaCompiler._wrapper("Generic.TrimAndRespond", {"bad) end Evil;": 1.0})
    with pytest.raises(ValueError, match="qualified enum names"):
        RumocaCompiler._wrapper(
            "Generic.TrimAndRespond",
            {"mode": "Enum.Good); end Evil; model Evil"},
        )


def test_rumoca_wrapper_is_deterministic_and_forces_msl_loading() -> None:
    first = RumocaCompiler._wrapper(
        "AHUs.MultiZone.VAV.Controller",
        {"z": 1.5, "a": True},
    )
    second = RumocaCompiler._wrapper(
        "AHUs.MultiZone.VAV.Controller",
        {"a": True, "z": 1.5},
    )

    assert first == second
    assert "(a=true,z=1.5)" in first
    assert "parameter Modelica.Units.SI.Time bactalkMslProbe" in first
