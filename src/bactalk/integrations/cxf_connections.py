from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Literal

from bactalk.integrations.cxf_arrays import scalarize_fixed_arrays
from bactalk.integrations.cxf_importer import INSTANCE_SCHEMAS

PortDirection = Literal["source", "sink"]
_SIMPLE_BOOLEAN_GUARD = re.compile(
    r"^\s*(?P<negated>not\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*$",
    re.IGNORECASE,
)


def _items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [value] if isinstance(value, dict) else []


def _class_name(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    for candidate in values:
        if not isinstance(candidate, str):
            continue
        name = candidate.rsplit("#", 1)[-1].removeprefix("ex:")
        if name in INSTANCE_SCHEMAS:
            return name
    return None


def _parameter_values(graph: list[dict[str, Any]]) -> dict[str, bool | int | float | str]:
    values: dict[str, bool | int | float | str] = {}
    for node in graph:
        node_types = node.get("@type", [])
        types = node_types if isinstance(node_types, list) else [node_types]
        if not any(
            isinstance(item, str) and item.rsplit("#", 1)[-1] in {"S231:Parameter", "Parameter"}
            for item in types
        ):
            continue
        identifier = node.get("@id")
        value: Any = node.get("S231:value")
        if isinstance(value, dict) and "@value" in value:
            raw = value["@value"]
            datatype = str(value.get("@type", ""))
            if datatype.endswith("boolean"):
                value = str(raw).lower() == "true"
            elif datatype.endswith(("integer", "int")):
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue
            elif datatype.endswith(("double", "decimal", "float")):
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
            else:
                value = raw
        if isinstance(identifier, str) and isinstance(value, (bool, int, float, str)):
            values[identifier] = value
    return values


def _resolve_boolean_guard(
    identifier: str,
    expression: Any,
    parameters: dict[str, bool | int | float | str],
) -> bool | None:
    if not isinstance(expression, str):
        return None
    scopes = identifier.split(".")[:-1]

    def resolve_parameter(name: str) -> bool | int | float | str | None:
        candidates = [
            ".".join([*scopes[:length], name]) for length in range(len(scopes), 0, -1)
        ]
        candidates.append(name)
        return next(
            (parameters[candidate] for candidate in candidates if candidate in parameters),
            None,
        )

    matched = _SIMPLE_BOOLEAN_GUARD.fullmatch(expression)
    if matched is not None:
        value = resolve_parameter(matched.group("name"))
        if isinstance(value, bool):
            return not value if matched.group("negated") else value

    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None

    def qualified_name(node: ast.AST) -> str | None:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        parts.append(current.id)
        return ".".join(reversed(parts))

    def evaluate(node: ast.AST) -> bool | int | float | str:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float, str)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id.lower() in {"true", "false"}:
                return node.id.lower() == "true"
            resolved = resolve_parameter(node.id)
            if resolved is None:
                raise ValueError(node.id)
            return resolved
        if isinstance(node, ast.Attribute):
            name = qualified_name(node)
            if name is None:
                raise ValueError("attribute")
            resolved = resolve_parameter(name)
            return name if resolved is None else resolved
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = evaluate(node.operand)
            if not isinstance(value, bool):
                raise ValueError("not-non-boolean")
            return not value
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [evaluate(value) for value in node.values]
            if not all(isinstance(value, bool) for value in values):
                raise ValueError("boolean-operator-non-boolean")
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left = evaluate(node.left)
            right = evaluate(node.comparators[0])
            operator = node.ops[0]
            if isinstance(operator, ast.Eq):
                return left == right
            if isinstance(operator, ast.NotEq):
                return left != right
        raise ValueError(type(node).__name__)

    try:
        result = evaluate(parsed)
    except (TypeError, ValueError):
        return None
    return result if isinstance(result, bool) else None


def _prune_proven_inactive_connections(
    graph: list[dict[str, Any]],
) -> dict[str, Any]:
    """Remove only wires beneath Boolean guards that are proven false.

    Modelica conditional declarations are compile-time structure. Some
    modelica-json CXF retains the declaration's connect equation even when its
    guard is false. Downstream validation must not see that wire as active.
    This pass recognizes a deliberately bounded Boolean subset: grounded
    parameters, enum equality/inequality, ``not``, ``and``, ``or``, and
    parentheses. Arithmetic, calls, indexing, and ungrounded names remain
    unchanged for fail-closed review.
    """

    parameters = _parameter_values(graph)
    inactive_roots: list[str] = []
    active_roots: list[str] = []
    evaluated: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    for node in graph:
        if node.get("S231:isConditionalComponent") is not True:
            continue
        identifier = node.get("@id")
        expression = node.get("S231:conditionalExpression")
        if not isinstance(identifier, str):
            continue
        result = _resolve_boolean_guard(identifier, expression, parameters)
        if result is None:
            unresolved.append({"component": identifier, "expression": str(expression)})
            continue
        evaluated.append({"component": identifier, "expression": expression, "active": result})
        if not result:
            inactive_roots.append(identifier)
        else:
            active_roots.append(identifier)

    for node in graph:
        if node.get("@id") not in active_roots:
            continue
        node.pop("S231:isConditionalComponent", None)
        node.pop("S231:conditionalExpression", None)

    def is_inactive(identifier: str) -> bool:
        return any(
            identifier == root or identifier.startswith(root + ".") for root in inactive_roots
        )

    pruned_edges: list[list[str]] = []
    for node in graph:
        source = node.get("@id")
        references = _items(node.get("S231:isConnectedTo"))
        if not isinstance(source, str) or not references:
            continue
        retained: list[dict[str, Any]] = []
        for reference in references:
            target = reference.get("@id")
            if isinstance(target, str) and (is_inactive(source) or is_inactive(target)):
                pruned_edges.append([source, target])
            else:
                retained.append(reference)
        if not retained:
            node.pop("S231:isConnectedTo", None)
        elif len(retained) == 1:
            node["S231:isConnectedTo"] = retained[0]
        else:
            node["S231:isConnectedTo"] = retained
    return {
        "evaluated_guard_count": len(evaluated),
        "inactive_component_count": len(inactive_roots),
        "active_component_count": len(active_roots),
        "pruned_connection_count": len(pruned_edges),
        "evaluated_guards": evaluated,
        "active_components": sorted(active_roots),
        "inactive_components": sorted(inactive_roots),
        "pruned_connections": sorted(pruned_edges),
        "unresolved_guard_count": len(unresolved),
        "unresolved_guards": unresolved,
    }


def _drop_proven_inactive_structure(
    raw_graph: list[Any], inactive_roots: list[str]
) -> dict[str, Any]:
    def is_inactive(identifier: str) -> bool:
        return any(
            identifier == root or identifier.startswith(root + ".") for root in inactive_roots
        )

    removed_nodes = [
        node.get("@id")
        for node in raw_graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str) and is_inactive(node["@id"])
    ]
    raw_graph[:] = [
        node
        for node in raw_graph
        if not (
            isinstance(node, dict) and isinstance(node.get("@id"), str) and is_inactive(node["@id"])
        )
    ]
    reference_keys = (
        "S231:containsBlock",
        "S231:hasInput",
        "S231:hasOutput",
        "S231:hasParameter",
        "S231:hasInstance",
        "S231:isConnectedTo",
    )
    removed_references: list[list[str]] = []
    for node in raw_graph:
        if not isinstance(node, dict):
            continue
        owner = str(node.get("@id", ""))
        for key in reference_keys:
            if key not in node:
                continue
            references = _items(node[key])
            retained: list[dict[str, Any]] = []
            for reference in references:
                target = reference.get("@id")
                if isinstance(target, str) and is_inactive(target):
                    removed_references.append([owner, key, target])
                else:
                    retained.append(reference)
            if not retained:
                node.pop(key, None)
            elif len(retained) == 1:
                node[key] = retained[0]
            else:
                node[key] = retained
    return {
        "removed_node_count": len(removed_nodes),
        "removed_nodes": sorted(removed_nodes),
        "removed_structural_reference_count": len(removed_references),
        "removed_structural_references": sorted(removed_references),
    }


def _ground_root_parameter_bounds(graph: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace bare connector bounds with already-grounded root parameter values.

    modelica-json may preserve ``min=p`` and ``max=p`` as the string ``"p"``
    even when the root declaration for ``p`` has a scalar value. OCE correctly
    rejects unresolved bounds, so perform only this unambiguous local lookup.
    Expressions, nested parameters, arrays, and missing values remain untouched.
    """

    roots = [node for node in graph if node.get("S231:containsBlock")]
    if len(roots) != 1:
        return {"grounded_bound_count": 0, "grounded_bounds": []}
    root = roots[0]
    nodes = {node["@id"]: node for node in graph if isinstance(node.get("@id"), str)}
    parameter_ids: list[str] = []
    for key in ("S231:hasParameter", "S231:hasInstance"):
        parameter_ids.extend(
            reference["@id"]
            for reference in _items(root.get(key))
            if isinstance(reference.get("@id"), str)
        )
    values: dict[str, int | float] = {}
    for identifier in parameter_ids:
        node = nodes.get(identifier, {})
        node_types = node.get("@type", [])
        types = node_types if isinstance(node_types, list) else [node_types]
        if not any(
            isinstance(item, str) and item.rsplit("#", 1)[-1] in {"S231:Parameter", "Parameter"}
            for item in types
        ):
            continue
        value = node.get("S231:value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        label = node.get("S231:label")
        local_name = identifier.rsplit(".", 1)[-1]
        values[local_name] = value
        if isinstance(label, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
            values[label] = value

    grounded: list[dict[str, Any]] = []
    for node in graph:
        identifier = node.get("@id")
        if not isinstance(identifier, str):
            continue
        for key in ("S231:min", "S231:max"):
            expression = node.get(key)
            if not isinstance(expression, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", expression
            ):
                continue
            if expression not in values:
                continue
            value = values[expression]
            node[key] = value
            grounded.append(
                {
                    "node": identifier,
                    "property": key,
                    "parameter": expression,
                    "value": value,
                }
            )
    return {
        "grounded_bound_count": len(grounded),
        "grounded_bounds": grounded,
    }


def _quote_assert_message_literals(graph: list[dict[str, Any]]) -> dict[str, Any]:
    """Encode modelica-json Assert messages as CDL string expressions.

    ``S231:value`` is an expression slot. modelica-json currently writes the
    human-readable ``CDL.Utilities.Assert.message`` payload directly into that
    slot, while OCE's expression grounder expects a quoted CDL string literal.
    The owning class and exact ``message`` instance make this repair
    unambiguous; no other string-valued parameter is changed.
    """

    nodes = {node.get("@id"): node for node in graph if isinstance(node.get("@id"), str)}
    normalized: list[dict[str, str]] = []
    assert_class = "Buildings.Controls.OBC.CDL.Utilities.Assert"
    for component in graph:
        raw_types = component.get("@type", [])
        types = raw_types if isinstance(raw_types, list) else [raw_types]
        if not any(
            isinstance(item, str)
            and item.rsplit("#", 1)[-1].removeprefix("ex:") == assert_class
            for item in types
        ):
            continue
        component_id = component.get("@id")
        for reference in _items(component.get("S231:hasInstance")):
            parameter_id = reference.get("@id")
            if not isinstance(parameter_id, str) or parameter_id.rsplit(".", 1)[-1] != "message":
                continue
            parameter = nodes.get(parameter_id)
            if parameter is None:
                continue
            value = parameter.get("S231:value")
            if not isinstance(value, str):
                continue
            already_quoted = False
            try:
                already_quoted = isinstance(json.loads(value), str)
            except (json.JSONDecodeError, TypeError):
                pass
            if already_quoted:
                continue
            parameter["S231:value"] = json.dumps(value, ensure_ascii=False)
            normalized.append(
                {
                    "component": str(component_id),
                    "parameter": parameter_id,
                    "message_sha256": hashlib.sha256(value.encode()).hexdigest(),
                }
            )
    return {
        "normalized_message_count": len(normalized),
        "normalized_messages": normalized,
        "policy": (
            "Only the reviewed CDL.Utilities.Assert.message instance contract is encoded "
            "as a quoted CDL string-literal expression."
        ),
    }


def _port_directions(
    graph: list[dict[str, Any]],
    identifiers: set[str] | None = None,
) -> dict[str, PortDirection]:
    nodes = {node["@id"]: node for node in graph if isinstance(node.get("@id"), str)}
    components = {
        identifier: class_name
        for identifier, node in nodes.items()
        if (class_name := _class_name(node.get("@type"))) is not None
    }
    directions: dict[str, PortDirection] = {}
    for identifier in identifiers or set(nodes):
        node = nodes.get(identifier, {})
        node_types = node.get("@type", [])
        values = node_types if isinstance(node_types, list) else [node_types]
        if any(isinstance(value, str) and value.endswith("Input") for value in values):
            # A controller boundary input is the signal source inside the graph.
            directions[identifier] = "source"
            continue
        if any(isinstance(value, str) and value.endswith("Output") for value in values):
            directions[identifier] = "sink"
            continue
        parent, separator, slot = identifier.rpartition(".")
        if not separator or parent not in components:
            continue
        schema = INSTANCE_SCHEMAS[components[parent]]
        if slot in schema["inputs"]:
            directions[identifier] = "sink"
        elif slot in schema["outputs"]:
            directions[identifier] = "source"
    return directions


def normalize_connection_sets(
    document: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Canonicalize exact Modelica connector sets into directed CXF links.

    Modelica ``connect`` equations form undirected connection sets. modelica-json
    normally emits the first argument as a directed CXF source, so a legal
    input-to-input join can look multiply driven even when the same set contains
    exactly one output. We rewrite only fully classified sets having exactly one
    source and one or more sinks. Ambiguous or unknown sets remain untouched and
    therefore continue to fail closed in the downstream validator.
    """

    prepared = copy.deepcopy(document)
    prepared_graph = prepared.get("@graph")
    if not isinstance(prepared_graph, list):
        raise ValueError("CXF document is missing its JSON-LD graph")
    prepared_nodes = [node for node in prepared_graph if isinstance(node, dict)]
    conditional_pruning = _prune_proven_inactive_connections(prepared_nodes)
    conditional_pruning.update(
        _drop_proven_inactive_structure(
            prepared_graph,
            conditional_pruning["inactive_components"],
        )
    )
    normalized, array_scalarization = scalarize_fixed_arrays(prepared)
    raw_graph = normalized.get("@graph")
    if not isinstance(raw_graph, list):
        raise ValueError("CXF document is missing its JSON-LD graph")
    graph = [node for node in raw_graph if isinstance(node, dict)]
    assert_message_normalization = _quote_assert_message_literals(graph)
    bound_grounding = _ground_root_parameter_bounds(graph)
    nodes = {node["@id"]: node for node in graph if isinstance(node.get("@id"), str)}
    adjacency: dict[str, set[str]] = defaultdict(set)
    directed_edges: set[tuple[str, str]] = set()
    for source, node in nodes.items():
        for reference in _items(node.get("S231:isConnectedTo")):
            target = reference.get("@id")
            if not isinstance(target, str):
                continue
            adjacency[source].add(target)
            adjacency[target].add(source)
            directed_edges.add((source, target))

    directions = _port_directions(graph, set(adjacency))
    visited: set[str] = set()
    rewrites: list[dict[str, Any]] = []
    examined = 0
    for start in sorted(adjacency):
        if start in visited:
            continue
        stack = [start]
        connection_set: set[str] = set()
        while stack:
            current = stack.pop()
            if current in connection_set:
                continue
            connection_set.add(current)
            stack.extend(adjacency[current] - connection_set)
        visited.update(connection_set)
        examined += 1
        if any(identifier not in directions for identifier in connection_set):
            continue
        sources = sorted(
            identifier for identifier in connection_set if directions[identifier] == "source"
        )
        sinks = sorted(
            identifier for identifier in connection_set if directions[identifier] == "sink"
        )
        if len(sources) != 1 or not sinks:
            continue
        source = sources[0]
        expected = {(source, sink) for sink in sinks}
        existing = {
            edge
            for edge in directed_edges
            if edge[0] in connection_set and edge[1] in connection_set
        }
        if existing == expected:
            continue
        for identifier in connection_set:
            if identifier in nodes:
                nodes[identifier].pop("S231:isConnectedTo", None)
        if source not in nodes:
            source_node = {"@id": source}
            raw_graph.append(source_node)
            nodes[source] = source_node
        references = [{"@id": sink} for sink in sinks]
        nodes[source]["S231:isConnectedTo"] = references[0] if len(references) == 1 else references
        rewrites.append(
            {
                "source": source,
                "sinks": sinks,
                "replaced_edges": [list(edge) for edge in sorted(existing)],
            }
        )

    return normalized, {
        "schema": "bactalk.cxf-connection-normalization/v5",
        "array_scalarization": array_scalarization,
        "assert_message_normalization": assert_message_normalization,
        "root_parameter_bound_grounding": bound_grounding,
        "conditional_pruning": conditional_pruning,
        "examined_connection_set_count": examined,
        "rewritten_connection_set_count": len(rewrites),
        "rewrites": rewrites,
        "policy": (
            "Only fully classified Modelica connection sets with exactly one source are "
            "rewritten; ambiguous sets remain unchanged for downstream rejection."
        ),
    }
