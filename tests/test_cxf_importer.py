import json
import zipfile
from pathlib import Path

import pytest

from bactalk.compiler import NiagaraCompiler
from bactalk.domain import BlockKind
from bactalk.integrations.cxf_importer import CxfImporter, CxfImportError
from bactalk.integrations.cxf_vectors import CxfVectorVerifier
from bactalk.integrations.g36_library import G36Library
from bactalk.integrations.open_control_engine import OpenControlEngine
from bactalk.integrations.open_control_library import OpenControlLibrary
from bactalk.simulator import GraphInterpreter

LIBRARY = Path(".vendor/open-control-library")
G36_SUPPLY_SIGNALS = Path(
    ".vendor/open-control-engine/third_party/modelica-buildings-cdl/cxf/Buildings/Controls/"
    "OBC/ASHRAE/G36/AHUs/MultiZone/VAV/SetPoints/SupplySignals.jsonld"
)


def test_real_fan_proof_cxf_translates_verifies_and_compiles(tmp_path: Path) -> None:
    source = LIBRARY / "faults/ahu/AHU-0039"
    importer = CxfImporter()
    graph = importer.import_graph(importer.load(source / "rule.cxf.jsonld"))
    vectors = json.loads((source / "vectors.json").read_text(encoding="utf-8"))
    report = CxfVectorVerifier().verify(graph, vectors)
    artifact = NiagaraCompiler().compile(graph, tmp_path / "fan-proof.bog")

    assert graph.metadata["coverage"]["translatable"] is True
    assert graph.metadata["coverage"]["component_count"] == 7
    assert report["passed"] is True
    assert report["scenario_count"] == 10
    with zipfile.ZipFile(artifact) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:BooleanDelay" in xml
    assert b"yFailToStart" in xml


def test_temporal_cxf_executes_exactly_and_fails_closed_for_niagara(tmp_path: Path) -> None:
    importer = CxfImporter()
    source = LIBRARY / "faults/ahu/AHU-0004"
    document = importer.load(source / "rule.cxf.jsonld")

    coverage = importer.inspect(document)
    graph = importer.import_graph(document)
    report = CxfVectorVerifier().verify(
        graph,
        json.loads((source / "vectors.json").read_text(encoding="utf-8")),
    )

    assert coverage["translatable"] is True
    assert coverage["niagara_translatable"] is False
    assert (
        "Buildings.Controls.OBC.CDL.Reals.MovingAverage" in coverage["niagara_unsupported_classes"]
    )
    assert report["passed"] is True
    with pytest.raises(ValueError, match="moving_average"):
        NiagaraCompiler().compile(graph, tmp_path / "unsupported.bog")


def test_unknown_cxf_class_reports_exact_gap_and_fails_closed() -> None:
    importer = CxfImporter()
    document = importer.load(LIBRARY / "faults/ahu/AHU-0039/rule.cxf.jsonld")
    root = next(node for node in document["@graph"] if node.get("S231:containsBlock"))
    component_id = root["S231:containsBlock"][0]["@id"]
    component = next(node for node in document["@graph"] if node.get("@id") == component_id)
    component["@type"] = "urn:test#Vendor.Controls.Magic"

    coverage = importer.inspect(document)

    assert coverage["translatable"] is False
    assert coverage["unsupported_classes"] == ["Vendor.Controls.Magic"]
    with pytest.raises(CxfImportError, match="cannot be lowered exactly"):
        importer.import_graph(document)


def test_modelica_json_compact_ex_prefix_is_normalized() -> None:
    importer = CxfImporter()
    document = importer.load(LIBRARY / "faults/ahu/AHU-0039/rule.cxf.jsonld")
    root = next(node for node in document["@graph"] if node.get("S231:containsBlock"))
    component_ids = {item["@id"] for item in root["S231:containsBlock"]}
    for node in document["@graph"]:
        if node.get("@id") in component_ids and isinstance(node.get("@type"), str):
            node["@type"] = "ex:" + node["@type"].rsplit("#", 1)[-1]

    coverage = importer.inspect(document)

    assert coverage["translatable"] is True
    assert coverage["unsupported_classes"] == []


def test_open_control_library_exposes_full_catalog_and_verified_translation() -> None:
    library = OpenControlLibrary(LIBRARY)

    catalog = library.catalog()
    graph, report = library.translate("AHU-0039")

    assert catalog["count"] == 137
    assert catalog["ir_vector_verified_count"] == 137
    assert catalog["niagara_vector_verified_count"] == 113
    assert len({rule["family"] for rule in catalog["rules"]}) == 14
    assert graph.name == "ahu_0039"
    assert report["passed"] is True


def test_current_modelica_json_g36_instances_lower_and_match_oce_trajectory() -> None:
    document = json.loads(G36_SUPPLY_SIGNALS.read_text(encoding="utf-8"))
    importer = CxfImporter()
    coverage = importer.inspect(document)
    graph = importer.import_graph(document)
    interface = G36Library._interface(document)
    public_inputs = {item["label"]: item["id"] for item in interface["inputs"]}
    public_outputs = {item["label"]: item["id"] for item in interface["outputs"]}
    rows = [
        (0.0, 292.15, 290.15, True),
        (60.0, 291.15, 290.15, True),
        (120.0, 289.15, 290.15, True),
        (180.0, 289.15, 290.15, False),
        (240.0, 289.15, 290.15, True),
        (300.0, 291.15, 290.15, True),
    ]
    samples = [
        {
            "time": timestamp,
            "inputs": {
                public_inputs["TAirSup"]: measured,
                public_inputs["TAirSupSet"]: setpoint,
                public_inputs["u1SupFan"]: fan,
            },
        }
        for timestamp, measured, setpoint, fan in rows
    ]
    oracle = OpenControlEngine().simulate_document(
        document,
        samples=samples,
        collect=list(public_outputs.values()),
    )
    interpreter = GraphInterpreter(graph)
    previous_time = 0.0
    observed: list[dict[str, float | bool]] = []
    for timestamp, measured, setpoint, fan in rows:
        values = interpreter.evaluate(
            {"TAirSup": measured, "TAirSupSet": setpoint, "u1SupFan": fan},
            step_seconds=0.0 if timestamp == 0.0 else timestamp - previous_time,
        )
        previous_time = timestamp
        observed.append({label: values[label] for label in public_outputs})

    assert coverage["translatable"] is True
    assert coverage["niagara_translatable"] is False
    assert coverage["unsupported_classes"] == []
    assert coverage["niagara_unsupported_classes"] == [
        "Buildings.Controls.OBC.CDL.Reals.PIDWithReset"
    ]
    assert sum(block.kind == BlockKind.PID_WITH_RESET for block in graph.blocks) == 1
    assert all(block.kind != BlockKind.RESET for block in graph.blocks)
    for actual, oracle_row in zip(observed, oracle["trace"], strict=True):
        for label, identifier in public_outputs.items():
            expected = oracle_row["outputs"][identifier]["value"]
            assert actual[label] == pytest.approx(expected, rel=0.0, abs=1e-14)


def test_line_has_instance_lowering_is_niagara_compilable(tmp_path: Path) -> None:
    root = "urn:test#LineProgram"
    line = f"{root}.line"
    input_names = ("x1", "f1", "x2", "f2", "u")
    graph_nodes: list[dict] = [
        {
            "@id": root,
            "@type": "S231:Block",
            "S231:label": "LineProgram",
            "S231:containsBlock": {"@id": line},
            "S231:hasInput": [{"@id": f"{root}.{name}"} for name in input_names],
            "S231:hasOutput": {"@id": f"{root}.y"},
        },
        {
            "@id": line,
            "@type": "urn:test#Buildings.Controls.OBC.CDL.Reals.Line",
            "S231:label": "line",
            "S231:hasInstance": [
                *({"@id": f"{line}.{name}"} for name in input_names),
                {"@id": f"{line}.limitBelow"},
                {"@id": f"{line}.limitAbove"},
                {"@id": f"{line}.y"},
            ],
        },
        {
            "@id": f"{line}.limitBelow",
            "S231:value": True,
        },
        {
            "@id": f"{line}.limitAbove",
            "S231:value": True,
        },
        {
            "@id": f"{line}.y",
            "S231:isConnectedTo": {"@id": f"{root}.y"},
        },
        {"@id": f"{root}.y", "@type": "S231:RealOutput", "S231:label": "y"},
    ]
    graph_nodes.extend(
        {
            "@id": f"{root}.{name}",
            "@type": "S231:RealInput",
            "S231:label": name,
            "S231:isConnectedTo": {"@id": f"{line}.{name}"},
        }
        for name in input_names
    )
    document = {"@graph": graph_nodes}

    graph = CxfImporter().import_graph(document)
    values = GraphInterpreter(graph).evaluate(
        {"x1": 0.0, "f1": 10.0, "x2": 20.0, "f2": 30.0, "u": 25.0},
        step_seconds=0.0,
    )
    artifact = NiagaraCompiler().compile(graph, tmp_path / "line.bog")

    assert values["y"] == 30.0
    assert artifact.stat().st_size > 0


def test_g36_zone_states_lowers_nor_and_preserves_integer_constants() -> None:
    translated = G36Library().translate("ThermalZones.ZoneStates")
    coverage = translated["lowering"]
    graph = translated["typed_ir"]

    assert coverage["translatable"] is True
    assert coverage["unsupported_classes"] == []
    assert graph is not None
    assert {block["kind"] for block in graph["blocks"]}.issuperset(
        {"or", "not", "hysteresis"}
    )

    def output(u_heating: float, u_cooling: float) -> float:
        interpreter = GraphInterpreter(
            G36Library().importer.import_graph(translated["cxf_document"])
        )
        return interpreter.evaluate(
            {"uHea": u_heating, "uCoo": u_cooling}, step_seconds=0.0
        )["yZonSta"]

    assert output(0.0, 0.0) == 2.0
    assert output(0.1, 0.0) == 1.0
    assert output(0.0, 0.1) == 3.0


def test_g36_symbolic_integer_constant_is_grounded() -> None:
    translated = G36Library().translate("AHUs.SingleZone.VAV.SetPoints.CoolingCoil")

    assert translated["lowering"]["translatable"] is True
    assert translated["lowering"]["unsupported_classes"] == []
    graph = translated["typed_ir"]
    assert graph is not None
    cooling_constants = [
        block
        for block in graph["blocks"]
        if block["kind"] == "numeric_const" and block["label"] == "conInt"
    ]
    assert [block["config"]["value"] for block in cooling_constants] == [3.0]


def test_triggered_sampler_lowers_to_exact_rising_edge_latch() -> None:
    root = "urn:test#TriggeredSample"
    sampler = f"{root}.sample"
    document = {
        "@graph": [
            {
                "@id": root,
                "@type": "S231:Block",
                "S231:label": "TriggeredSample",
                "S231:containsBlock": {"@id": sampler},
                "S231:hasInput": [
                    {"@id": f"{root}.u"},
                    {"@id": f"{root}.trigger"},
                ],
                "S231:hasOutput": {"@id": f"{root}.y"},
            },
            {
                "@id": sampler,
                "@type": (
                    "urn:test#Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler"
                ),
                "S231:label": "sample",
                "S231:hasInstance": [
                    {"@id": f"{sampler}.u"},
                    {"@id": f"{sampler}.trigger"},
                    {"@id": f"{sampler}.y_start"},
                    {"@id": f"{sampler}.y"},
                ],
            },
            {
                "@id": f"{root}.u",
                "@type": "S231:RealInput",
                "S231:label": "u",
                "S231:isConnectedTo": {"@id": f"{sampler}.u"},
            },
            {
                "@id": f"{root}.trigger",
                "@type": "S231:BooleanInput",
                "S231:label": "trigger",
                "S231:isConnectedTo": {"@id": f"{sampler}.trigger"},
            },
            {
                "@id": f"{sampler}.y_start",
                "S231:value": 4.0,
            },
            {
                "@id": f"{sampler}.y",
                "S231:isConnectedTo": {"@id": f"{root}.y"},
            },
            {"@id": f"{root}.y", "@type": "S231:RealOutput", "S231:label": "y"},
        ]
    }

    importer = CxfImporter()
    coverage = importer.inspect(document)
    interpreter = GraphInterpreter(importer.import_graph(document))

    assert coverage["translatable"] is True
    assert coverage["niagara_translatable"] is False
    assert interpreter.evaluate({"u": 10.0, "trigger": False})["y"] == 4.0
    assert interpreter.evaluate({"u": 10.0, "trigger": True})["y"] == 10.0
    assert interpreter.evaluate({"u": 20.0, "trigger": True})["y"] == 10.0
    interpreter.evaluate({"u": 20.0, "trigger": False})
    assert interpreter.evaluate({"u": 20.0, "trigger": True})["y"] == 20.0


@pytest.mark.parametrize(
    ("controller_type", "expected", "edge_count"),
    [
        ("PI", [0.0, 0.1, 0.1, 0.15, 0.0, 0.1], 1),
        ("P", [0.0, 0.5, 0.5, 0.5, 0.0, 0.5], 0),
    ],
)
def test_pid_with_enable_composite_preserves_enable_and_reset_contract(
    controller_type: str,
    expected: list[float],
    edge_count: int,
) -> None:
    root = "urn:test#PIDWithEnable"
    controller = f"{root}.controller"
    parameters = {
        "controllerType": (
            "Buildings.Controls.OBC.CDL.Types.SimpleController." + controller_type
        ),
        "k": 1.0,
        "Ti": 10.0,
        "r": 1.0,
        "yMax": 1.0,
        "yMin": 0.0,
        "Ni": 0.9,
        "reverseActing": True,
        "y_reset": 0.1,
        "y_neutral": 0.0,
    }
    instances = ["u_s", "u_m", "uEna", "y", *parameters]
    document = {
        "@graph": [
            {
                "@id": root,
                "@type": "S231:Block",
                "S231:label": "PIDWithEnable",
                "S231:containsBlock": {"@id": controller},
                "S231:hasInput": [
                    {"@id": f"{root}.u_s"},
                    {"@id": f"{root}.u_m"},
                    {"@id": f"{root}.uEna"},
                ],
                "S231:hasOutput": {"@id": f"{root}.y"},
            },
            {
                "@id": controller,
                "@type": "urn:test#Utilities.PIDWithEnable",
                "S231:label": "controller",
                "S231:hasInstance": [
                    {"@id": f"{controller}.{name}"} for name in instances
                ],
            },
            {
                "@id": f"{root}.u_s",
                "@type": "S231:RealInput",
                "S231:label": "u_s",
                "S231:isConnectedTo": {"@id": f"{controller}.u_s"},
            },
            {
                "@id": f"{root}.u_m",
                "@type": "S231:RealInput",
                "S231:label": "u_m",
                "S231:isConnectedTo": {"@id": f"{controller}.u_m"},
            },
            {
                "@id": f"{root}.uEna",
                "@type": "S231:BooleanInput",
                "S231:label": "uEna",
                "S231:isConnectedTo": {"@id": f"{controller}.uEna"},
            },
            {
                "@id": f"{controller}.y",
                "S231:isConnectedTo": {"@id": f"{root}.y"},
            },
            {"@id": f"{root}.y", "@type": "S231:RealOutput", "S231:label": "y"},
            *(
                {"@id": f"{controller}.{name}", "S231:value": value}
                for name, value in parameters.items()
            ),
        ]
    }

    importer = CxfImporter()
    coverage = importer.inspect(document)
    graph = importer.import_graph(document)
    interpreter = GraphInterpreter(graph)
    observed = []
    for index, enabled in enumerate([False, True, True, True, False, True]):
        observed.append(
            interpreter.evaluate(
                {"u_s": 0.5, "u_m": 0.0, "uEna": enabled},
                step_seconds=0.0 if index == 0 else 1.0,
            )["y"]
        )

    assert coverage["translatable"] is True
    assert coverage["niagara_unsupported_classes"] == ["Utilities.PIDWithEnable"]
    assert observed == pytest.approx(expected)
    assert sum(block.kind == BlockKind.ONE_SHOT for block in graph.blocks) == edge_count
