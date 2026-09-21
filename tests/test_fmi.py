from __future__ import annotations

import io
import zipfile

import pytest

from bactalk.integrations.fmi import inspect_fmu_archive


def _fmu(description: str, *members: tuple[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("modelDescription.xml", description)
        for name, content in members:
            archive.writestr(name, content)
    return stream.getvalue()


def test_inspect_fmi_two_variables_and_platform() -> None:
    content = _fmu(
        """<fmiModelDescription fmiVersion="2.0" modelName="Office"
  guid="abc" generationTool="Modelica">
  <CoSimulation modelIdentifier="office_cs" />
  <ModelVariables>
    <ScalarVariable name="fan_u" valueReference="1" causality="input"
      variability="continuous" description="Fan command">
      <Real unit="1" min="0" max="1" start="0" />
    </ScalarVariable>
    <ScalarVariable name="zone_T" valueReference="2" causality="output"
      variability="continuous">
      <Real unit="K" start="293.15" />
    </ScalarVariable>
    <ScalarVariable name="gain" valueReference="3" causality="parameter"
      variability="fixed">
      <Real start="2" />
    </ScalarVariable>
  </ModelVariables>
</fmiModelDescription>""",
        ("binaries/darwin64/office_cs.dylib", b"binary"),
    )

    result = inspect_fmu_archive(content, filename="office.fmu")

    assert result.filename == "office.fmu"
    assert result.fmi_version == "2.0"
    assert result.model_name == "Office"
    assert result.model_identifiers == ["office_cs"]
    assert result.platforms == ["darwin64"]
    assert result.variable_count == 3
    assert result.inputs[0].model_dump() == {
        "name": "fan_u",
        "value_reference": "1",
        "causality": "input",
        "variability": "continuous",
        "initial": None,
        "data_type": "Real",
        "unit": "1",
        "minimum": "0",
        "maximum": "1",
        "start": "0",
        "description": "Fan command",
    }
    assert result.outputs[0].unit == "K"
    assert result.parameter_count == 1
    assert result.local_variable_count == 0
    assert result.live_building_writes is False


def test_inspect_fmi_three_typed_variables() -> None:
    content = _fmu(
        """<fmiModelDescription fmiVersion="3.0" modelName="Office3" instantiationToken="xyz">
  <ModelExchange modelIdentifier="office_me" />
  <ModelVariables>
    <Float64 name="valve_u" valueReference="1" causality="input"
      variability="continuous" unit="1" min="0" max="1" start="0" />
    <Boolean name="proof_y" valueReference="2" causality="output"
      variability="discrete" />
  </ModelVariables>
</fmiModelDescription>"""
    )

    result = inspect_fmu_archive(content)

    assert result.fmi_version == "3.0"
    assert result.instantiation_token == "xyz"
    assert result.inputs[0].data_type == "Float64"
    assert result.outputs[0].data_type == "Boolean"


@pytest.mark.parametrize(
    ("description", "message"),
    [
        ("<notFmi />", "invalid modelDescription"),
        (
            '<fmiModelDescription fmiVersion="2.0" modelName="x" guid="x" />',
            "no ModelVariables",
        ),
        (
            '<!DOCTYPE x [<!ENTITY bad "x">]><fmiModelDescription />',
            "forbidden declarations",
        ),
    ],
)
def test_inspect_rejects_invalid_descriptions(description: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        inspect_fmu_archive(_fmu(description))
