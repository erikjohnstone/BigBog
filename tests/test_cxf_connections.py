from __future__ import annotations

import json

from bactalk.integrations.cxf_connections import normalize_connection_sets


def test_normalize_modelica_connection_set_with_one_exact_driver() -> None:
    source = "ex:Root.constant.y"
    first_sink = "ex:Root.line.u"
    second_sink = "ex:Root.line.f1"
    document = {
        "@context": {"ex": "http://example.org#"},
        "@graph": [
            {
                "@id": "ex:Root.constant",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
            },
            {
                "@id": "ex:Root.line",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Line",
            },
            {"@id": source, "S231:isConnectedTo": {"@id": first_sink}},
            {"@id": second_sink, "S231:isConnectedTo": {"@id": first_sink}},
        ],
    }

    normalized, report = normalize_connection_sets(document)

    assert report["rewritten_connection_set_count"] == 1
    assert document["@graph"][2]["S231:isConnectedTo"] == {"@id": first_sink}
    nodes = {node["@id"]: node for node in normalized["@graph"]}
    assert nodes[source]["S231:isConnectedTo"] == [
        {"@id": second_sink},
        {"@id": first_sink},
    ]
    assert "S231:isConnectedTo" not in nodes[second_sink]


def test_ambiguous_connection_set_is_left_for_validator_to_reject() -> None:
    document = {
        "@graph": [
            {
                "@id": "ex:Root.a",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
            },
            {
                "@id": "ex:Root.b",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
            },
            {"@id": "ex:Root.a.y", "S231:isConnectedTo": {"@id": "ex:Root.b.y"}},
        ]
    }

    normalized, report = normalize_connection_sets(document)

    assert normalized == document
    assert report["rewritten_connection_set_count"] == 0


def test_proven_inactive_conditional_connections_are_pruned() -> None:
    inactive_output = "ex:Root.fallback.y"
    active_output = "ex:Root.primary.y"
    sink = "ex:Root.choice.u"
    document = {
        "@graph": [
            {
                "@id": "ex:Root",
                "@type": "S231:Block",
                "S231:containsBlock": [
                    {"@id": "ex:Root.fallback"},
                    {"@id": "ex:Root.primary"},
                    {"@id": "ex:Root.choice"},
                ],
            },
            {
                "@id": "ex:Root.use_primary",
                "@type": "S231:Parameter",
                "S231:value": True,
            },
            {
                "@id": "ex:Root.fallback",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
                "S231:isConditionalComponent": True,
                "S231:conditionalExpression": "not use_primary",
            },
            {
                "@id": "ex:Root.primary",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
                "S231:isConditionalComponent": True,
                "S231:conditionalExpression": "use_primary",
            },
            {
                "@id": "ex:Root.choice",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Add",
            },
            {"@id": inactive_output, "S231:isConnectedTo": {"@id": sink}},
            {"@id": active_output, "S231:isConnectedTo": {"@id": sink}},
        ]
    }

    normalized, report = normalize_connection_sets(document)

    nodes = {node["@id"]: node for node in normalized["@graph"]}
    pruning = report["conditional_pruning"]
    assert pruning["inactive_components"] == ["ex:Root.fallback"]
    assert pruning["pruned_connections"] == [[inactive_output, sink]]
    assert "ex:Root.fallback" not in nodes
    assert inactive_output not in nodes
    assert pruning["removed_node_count"] == 2
    assert nodes["ex:Root"]["S231:containsBlock"] == [
        {"@id": "ex:Root.primary"},
        {"@id": "ex:Root.choice"},
    ]
    assert "S231:isConditionalComponent" not in nodes["ex:Root.primary"]
    assert "S231:conditionalExpression" not in nodes["ex:Root.primary"]
    assert pruning["active_components"] == ["ex:Root.primary"]
    assert nodes[active_output]["S231:isConnectedTo"] == {"@id": sink}


def test_unknown_conditional_guard_remains_for_downstream_rejection() -> None:
    document = {
        "@graph": [
            {
                "@id": "ex:Root.conditional",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
                "S231:isConditionalComponent": True,
                "S231:conditionalExpression": "a and b",
            },
            {
                "@id": "ex:Root.conditional.y",
                "S231:isConnectedTo": {"@id": "ex:Root.sink.u"},
            },
        ]
    }

    normalized, report = normalize_connection_sets(document)

    assert normalized == document
    assert report["conditional_pruning"]["unresolved_guard_count"] == 1
    assert report["conditional_pruning"]["pruned_connection_count"] == 0


def test_grounded_enum_and_boolean_conditional_guard_is_pruned_exactly() -> None:
    enum_value = "Buildings.Controls.OBC.ASHRAE.G36.Types.FreezeStat.No_freeze_stat"
    document = {
        "@graph": [
            {
                "@id": "ex:Root.freezeStat",
                "@type": "S231:Parameter",
                "S231:value": enum_value,
            },
            {
                "@id": "ex:Root.enabled",
                "@type": "S231:Parameter",
                "S231:value": True,
            },
            {
                "@id": "ex:Root.conditional",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
                "S231:isConditionalComponent": True,
                "S231:conditionalExpression": (
                    "freezeStat == Buildings.Controls.OBC.ASHRAE.G36.Types."
                    "FreezeStat.Hardwired_to_BAS and enabled"
                ),
            },
            {
                "@id": "ex:Root.conditional.y",
                "S231:isConnectedTo": {"@id": "ex:Root.sink.u"},
            },
        ]
    }

    normalized, report = normalize_connection_sets(document)
    nodes = {node["@id"]: node for node in normalized["@graph"]}

    assert "ex:Root.conditional" not in nodes
    assert "ex:Root.conditional.y" not in nodes
    assert report["conditional_pruning"]["evaluated_guard_count"] == 1
    assert report["conditional_pruning"]["inactive_component_count"] == 1


def test_bare_root_parameter_connector_bounds_are_grounded_narrowly() -> None:
    document = {
        "@graph": [
            {
                "@id": "ex:Root",
                "@type": "S231:Block",
                "S231:containsBlock": {"@id": "ex:Root.constant"},
                "S231:hasParameter": [
                    {"@id": "ex:Root.low"},
                    {"@id": "ex:Root.high"},
                ],
            },
            {
                "@id": "ex:Root.low",
                "@type": "S231:Parameter",
                "S231:label": "low",
                "S231:value": 0.0,
            },
            {
                "@id": "ex:Root.high",
                "@type": "S231:Parameter",
                "S231:label": "high",
                "S231:value": 1.0,
            },
            {
                "@id": "ex:Root.output",
                "@type": "S231:RealOutput",
                "S231:min": "low",
                "S231:max": "high",
            },
            {
                "@id": "ex:Root.unknown",
                "@type": "S231:RealOutput",
                "S231:min": "low + 1",
            },
            {
                "@id": "ex:Root.constant",
                "@type": "ex:Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
            },
        ]
    }

    normalized, report = normalize_connection_sets(document)
    nodes = {node["@id"]: node for node in normalized["@graph"]}

    assert nodes["ex:Root.output"]["S231:min"] == 0.0
    assert nodes["ex:Root.output"]["S231:max"] == 1.0
    assert nodes["ex:Root.unknown"]["S231:min"] == "low + 1"
    assert report["root_parameter_bound_grounding"]["grounded_bound_count"] == 2


def test_assert_message_is_encoded_as_exact_cdl_string_expression() -> None:
    message = 'Warning: airflow is less than 50% of the setpoint. "Check" \\ sensor.'
    document = {
        "@graph": [
            {
                "@id": "ex:Root.assertion",
                "@type": "ex:Buildings.Controls.OBC.CDL.Utilities.Assert",
                "S231:hasInstance": [
                    {"@id": "ex:Root.assertion.message"},
                    {"@id": "ex:Root.assertion.u"},
                ],
            },
            {"@id": "ex:Root.assertion.message", "S231:value": message},
            {"@id": "ex:Root.unrelated.message", "S231:value": message},
        ]
    }

    normalized, report = normalize_connection_sets(document)
    nodes = {node["@id"]: node for node in normalized["@graph"]}

    assert nodes["ex:Root.assertion.message"]["S231:value"] == json.dumps(message)
    assert nodes["ex:Root.unrelated.message"]["S231:value"] == message
    assert report["assert_message_normalization"]["normalized_message_count"] == 1
