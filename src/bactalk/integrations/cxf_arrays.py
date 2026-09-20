from __future__ import annotations

import ast
import copy
import json
import math
import re
from collections import defaultdict
from itertools import product
from typing import Any
from urllib.parse import unquote

from bactalk.integrations.cxf_importer import (
    INSTANCE_SCHEMAS,
    PLACEHOLDER_CLASSES,
    resolve_parameter_expression,
)

_VECTOR_REPLICATORS = {
    "Buildings.Controls.OBC.CDL.Routing.BooleanVectorReplicator": "boolean",
    "Buildings.Controls.OBC.CDL.Routing.RealVectorReplicator": "real",
}
_VECTOR_FILTERS = {
    "Buildings.Controls.OBC.CDL.Routing.BooleanVectorFilter",
    "Buildings.Controls.OBC.CDL.Routing.RealVectorFilter",
}
_REDUCTIONS = {
    "Buildings.Controls.OBC.CDL.Logical.MultiOr": "Buildings.Controls.OBC.CDL.Logical.Or",
    "Buildings.Controls.OBC.CDL.Logical.MultiAnd": "Buildings.Controls.OBC.CDL.Logical.And",
    "Buildings.Controls.OBC.CDL.Reals.MultiSum": "Buildings.Controls.OBC.CDL.Reals.Add",
    "Buildings.Controls.OBC.CDL.Integers.MultiSum": "Buildings.Controls.OBC.CDL.Integers.Add",
    "Buildings.Controls.OBC.CDL.Reals.MultiMax": "Buildings.Controls.OBC.CDL.Reals.Max",
    "Buildings.Controls.OBC.CDL.Reals.MultiMin": "Buildings.Controls.OBC.CDL.Reals.Min",
    "Buildings.Templates.Plants.Controls.Utilities.MultiMaxInteger": (
        "Buildings.Controls.OBC.CDL.Integers.Max"
    ),
    "Utilities.MultiMaxInteger": "Buildings.Controls.OBC.CDL.Integers.Max",
    "Buildings.Templates.Plants.Controls.Utilities.MultiMinInteger": (
        "Buildings.Controls.OBC.CDL.Integers.Min"
    ),
    "Utilities.MultiMinInteger": "Buildings.Controls.OBC.CDL.Integers.Min",
}
_SCALAR_REPLICATORS = {
    "Buildings.Controls.OBC.CDL.Routing.BooleanScalarReplicator",
    "Buildings.Controls.OBC.CDL.Routing.RealScalarReplicator",
}
_MATRIX_GAIN = "Buildings.Controls.OBC.CDL.Reals.MatrixGain"
_LIMITER = "Buildings.Controls.OBC.CDL.Reals.Limiter"
_ARRAY_FIELDS = ("S231:isArray", "S231:numberDimensions", "S231:sizeOfDimensions")


class CxfArrayScalarizationError(ValueError):
    """Raised when a reviewed array construct cannot be expanded exactly."""


def _items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [value] if isinstance(value, dict) else []


def _refs(node: dict[str, Any], key: str) -> list[str]:
    return [item["@id"] for item in _items(node.get(key)) if isinstance(item.get("@id"), str)]


def _set_refs(node: dict[str, Any], key: str, identifiers: list[str]) -> None:
    if not identifiers:
        node.pop(key, None)
        return
    references = [{"@id": identifier} for identifier in identifiers]
    node[key] = references[0] if len(references) == 1 else references


def _class_name(node: dict[str, Any]) -> str:
    raw = node.get("@type", "")
    values = raw if isinstance(raw, list) else [raw]
    for value in values:
        if isinstance(value, str):
            return value.rsplit("#", 1)[-1].removeprefix("ex:")
    return ""


def _literal(value: Any) -> Any:
    if isinstance(value, dict) and "@value" in value:
        raw = value["@value"]
        datatype = str(value.get("@type", ""))
        if datatype.endswith("boolean"):
            return str(raw).lower() == "true"
        if datatype.endswith(("integer", "int")):
            return int(raw)
        if datatype.endswith(("double", "decimal", "float")):
            return float(raw)
        return raw
    return value


def _root_parameters(
    root: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> dict[str, int | float | bool | str]:
    values: dict[str, int | float | bool | str] = {}
    for identifier in _refs(root, "S231:hasParameter"):
        node = by_id.get(identifier)
        if node is None or "S231:value" not in node:
            continue
        value = _literal(node["S231:value"])
        if isinstance(value, (bool, int, float, str)):
            values[identifier.rsplit(".", 1)[-1]] = value
    for _ in range(max(1, len(values))):
        changed = False
        for name, value in list(values.items()):
            if isinstance(value, str) and value in values and values[value] != value:
                values[name] = values[value]
                changed = True
        if not changed:
            break
    return values


def _positive_dimension(value: Any, *, context: str) -> int:
    value = _literal(value)
    if isinstance(value, bool):
        raise CxfArrayScalarizationError(f"{context} is Boolean, not an array dimension")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value.strip()):
        value = int(value)
    if not isinstance(value, int) or not 1 <= value <= 512:
        raise CxfArrayScalarizationError(f"{context} must resolve to an integer from 1 to 512")
    return value


def _resolve_dimension(
    expression: Any,
    values: dict[str, int | float | bool | str],
    *,
    context: str,
) -> int:
    if isinstance(expression, str) and expression in values:
        expression = values[expression]
    return _positive_dimension(expression, context=context)


def _shape(
    node: dict[str, Any],
    values: dict[str, int | float | bool | str],
) -> tuple[int, ...]:
    identifier = str(node.get("@id", "array"))
    raw = node.get("S231:sizeOfDimensions")
    if not isinstance(raw, str) or not re.fullmatch(
        r"\(\s*[A-Za-z0-9_]+(?:\s*,\s*[A-Za-z0-9_]+)*\s*\)", raw
    ):
        raise CxfArrayScalarizationError(
            f"{identifier} has an unsupported fixed-array dimension declaration"
        )
    dimensions = tuple(
        _resolve_dimension(token.strip(), values, context=f"{identifier} dimension {token.strip()}")
        for token in raw[1:-1].split(",")
    )
    declared = node.get("S231:numberDimensions")
    if declared is not None and declared != len(dimensions):
        raise CxfArrayScalarizationError(f"{identifier} dimension count does not match {raw}")
    if math.prod(dimensions) > 4_096:
        raise CxfArrayScalarizationError(f"{identifier} exceeds 4096 scalar elements")
    return dimensions


def _indices(shape: tuple[int, ...]) -> list[tuple[int, ...]]:
    return list(product(*(range(1, dimension + 1) for dimension in shape)))


def _scalar_id(identifier: str, index: tuple[int, ...]) -> str:
    return identifier + "__" + "_".join(str(value) for value in index)


def _endpoint_selection(
    identifier: str,
    endpoint_maps: dict[str, dict[tuple[int, ...], str]],
    endpoint_shapes: dict[str, tuple[int, ...]],
) -> tuple[tuple[int, ...], dict[tuple[int, ...], str]] | None:
    """Resolve a whole connector or one explicit Modelica array element.

    rdflib percent-encodes brackets in connector IRIs, so accept both encoded
    and literal forms. Only positive, fully concrete one-based indices are
    admitted; symbolic and sliced endpoints remain fail-closed.
    """

    if identifier in endpoint_maps:
        return endpoint_shapes[identifier], endpoint_maps[identifier]
    decoded = unquote(identifier)
    matched = re.fullmatch(r"(.+)\[([1-9][0-9]*(?:,[1-9][0-9]*)*)\]", decoded)
    if matched is None:
        return None
    base = matched.group(1)
    if base not in endpoint_maps and "#" in base:
        local = base.split("#", 1)[1]
        candidates = [
            candidate
            for candidate in endpoint_maps
            if candidate.endswith(f":{local}") or candidate.endswith(f"#{local}")
        ]
        if len(candidates) > 1:
            raise CxfArrayScalarizationError(
                f"array endpoint {identifier} has ambiguous compact-IRI matches"
            )
        if candidates:
            base = candidates[0]
    if base not in endpoint_maps:
        return None
    index = tuple(int(value) for value in matched.group(2).split(","))
    selected = endpoint_maps[base].get(index)
    if selected is None:
        raise CxfArrayScalarizationError(
            f"array endpoint {identifier} is outside declared shape {endpoint_shapes[base]}"
        )
    return (), {(): selected}


def _scalar_connector(node: dict[str, Any], index: tuple[int, ...]) -> dict[str, Any]:
    scalar = copy.deepcopy(node)
    scalar["@id"] = _scalar_id(str(node["@id"]), index)
    for key in _ARRAY_FIELDS:
        scalar.pop(key, None)
    scalar.pop("S231:isConnectedTo", None)
    base_label = str(node.get("S231:label", str(node["@id"]).rsplit(".", 1)[-1]))
    base_label = re.sub(r"\s*\[[^]]*\]\s*$", "", base_label)
    scalar["S231:label"] = base_label + "__" + "_".join(str(value) for value in index)
    return scalar


def _component(
    identifier: str,
    class_name: str,
    label: str,
    instances: list[str],
) -> dict[str, Any]:
    return {
        "@id": identifier,
        "@type": f"ex:{class_name}",
        "S231:accessSpecifier": "protected",
        "S231:description": "BACTalk exact fixed-array scalarization",
        "S231:hasInstance": [{"@id": item} for item in instances],
        "S231:label": label,
    }


def _port(identifier: str, targets: list[str] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"@id": identifier}
    if targets:
        _set_refs(node, "S231:isConnectedTo", targets)
    return node


def _connected_components(graph: list[dict[str, Any]]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for node in graph:
        source = node.get("@id")
        if not isinstance(source, str):
            continue
        for reference in _items(node.get("S231:isConnectedTo")):
            target = reference.get("@id")
            if not isinstance(target, str):
                continue
            adjacency[source].add(target)
            adjacency[target].add(source)
    membership: dict[str, set[str]] = {}
    for start in sorted(adjacency):
        if start in membership:
            continue
        members: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current in members:
                continue
            members.add(current)
            stack.extend(adjacency[current] - members)
        for member in members:
            membership[member] = members
    return membership


def _component_parameter(
    component_id: str,
    name: str,
    by_id: dict[str, dict[str, Any]],
    root_values: dict[str, int | float | bool | str],
) -> int:
    identifier = f"{component_id}.{name}"
    node = by_id.get(identifier)
    if node is None or "S231:value" not in node:
        raise CxfArrayScalarizationError(f"{identifier} is missing")
    return _resolve_dimension(_literal(node["S231:value"]), root_values, context=identifier)


def _parse_array_expression(
    expression: Any,
    root_values: dict[str, int | float | bool | str],
    *,
    context: str,
) -> list[Any]:
    expression = _literal(expression)
    if isinstance(expression, str) and expression in root_values:
        expression = root_values[expression]
    if isinstance(expression, list):
        return expression
    if not isinstance(expression, str):
        raise CxfArrayScalarizationError(f"{context} is not a fixed array expression")
    stripped = expression.strip()

    def evaluate_scalar(value: str) -> int | float | bool:
        try:
            parsed = ast.parse(value, mode="eval")
        except SyntaxError as exc:
            raise CxfArrayScalarizationError(
                f"{context} contains an invalid scalar expression"
            ) from exc

        def evaluate(node: ast.AST) -> int | float | bool:
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float)):
                return node.value
            if isinstance(node, ast.Name):
                if node.id.lower() in {"true", "false"}:
                    return node.id.lower() == "true"
                resolved = root_values.get(node.id)
                if isinstance(resolved, bool) or not isinstance(resolved, (int, float)):
                    raise CxfArrayScalarizationError(
                        f"{context} contains ungrounded name {node.id}"
                    )
                return resolved
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                operand = evaluate(node.operand)
                if isinstance(operand, bool):
                    raise CxfArrayScalarizationError(f"{context} uses Boolean arithmetic")
                return operand if isinstance(node.op, ast.UAdd) else -operand
            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
            ):
                left = evaluate(node.left)
                right = evaluate(node.right)
                if isinstance(left, bool) or isinstance(right, bool):
                    raise CxfArrayScalarizationError(f"{context} uses Boolean arithmetic")
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                return left / right
            raise CxfArrayScalarizationError(
                f"{context} contains unsupported scalar expression {value!r}"
            )

        result = evaluate(parsed)
        if isinstance(result, float) and not math.isfinite(result):
            raise CxfArrayScalarizationError(f"{context} contains a non-finite value")
        return result

    fill = re.fullmatch(r"fill\(\s*(.+?)\s*,\s*([A-Za-z0-9_]+)\s*\)", stripped)
    if fill is not None:
        count = _resolve_dimension(fill.group(2), root_values, context=f"{context} fill count")
        return [evaluate_scalar(fill.group(1))] * count
    one_based_range = re.fullmatch(
        r"\{\s*([A-Za-z_][A-Za-z0-9_]*)\s+for\s+\1\s+in\s+1\s*:\s*"
        r"([A-Za-z0-9_]+)\s*\}",
        stripped,
    )
    if one_based_range is not None:
        count = _resolve_dimension(
            one_based_range.group(2),
            root_values,
            context=f"{context} comprehension bound",
        )
        return list(range(1, count + 1))
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise CxfArrayScalarizationError(
            f"{context} uses an unsupported array expression {expression!r}"
        )
    as_json = stripped.replace("{", "[").replace("}", "]")
    try:
        parsed = json.loads(as_json)
    except json.JSONDecodeError as exc:
        raise CxfArrayScalarizationError(f"{context} is not a literal rectangular array") from exc
    if not isinstance(parsed, list):
        raise CxfArrayScalarizationError(f"{context} is not an array")
    return parsed


class _DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, first: str, second: str) -> None:
        left = self.find(first)
        right = self.find(second)
        if left != right:
            self.parent[right] = left

    def groups(self) -> list[set[str]]:
        grouped: dict[str, set[str]] = defaultdict(set)
        for item in self.parent:
            grouped[self.find(item)].add(item)
        return list(grouped.values())


def _scalarize_filter_reduction_network(
    document: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Elaborate fixed component arrays, vector filters, and reductions."""

    raw_graph = document.get("@graph")
    if not isinstance(raw_graph, list):
        return None
    graph = [node for node in raw_graph if isinstance(node, dict)]
    roots = [node for node in graph if node.get("S231:containsBlock")]
    if len(roots) != 1:
        return None
    root = roots[0]
    by_id = {node["@id"]: node for node in graph if isinstance(node.get("@id"), str)}
    component_ids = _refs(root, "S231:containsBlock")
    components = [by_id.get(identifier) for identifier in component_ids]
    if any(component is None for component in components):
        return None
    classes = [_class_name(component or {}) for component in components]
    elaborated_classes = (
        _VECTOR_FILTERS | set(_REDUCTIONS) | _SCALAR_REPLICATORS | {_MATRIX_GAIN, _LIMITER}
    )
    if not any(class_name in elaborated_classes for class_name in classes):
        return None
    admitted = set(INSTANCE_SCHEMAS) | elaborated_classes
    if any(class_name not in admitted for class_name in classes):
        return None

    root_values = _root_parameters(root, by_id)
    input_ids = _refs(root, "S231:hasInput")
    output_ids = _refs(root, "S231:hasOutput")
    parameter_ids = _refs(root, "S231:hasParameter")
    endpoint_maps: dict[str, dict[tuple[int, ...], str]] = {}
    endpoint_shapes: dict[str, tuple[int, ...]] = {}
    directions: dict[str, str] = {}
    node_by_id: dict[str, dict[str, Any]] = {}
    generated_nodes: list[dict[str, Any]] = []
    new_component_ids: list[str] = []
    disjoint = _DisjointSet()

    def register(node: dict[str, Any], direction: str | None = None) -> None:
        identifier = node.get("@id")
        if not isinstance(identifier, str):
            raise CxfArrayScalarizationError("generated scalar node is missing @id")
        if identifier in node_by_id:
            raise CxfArrayScalarizationError(f"duplicate scalarized CXF node {identifier}")
        node_by_id[identifier] = node
        generated_nodes.append(node)
        if direction is not None:
            directions[identifier] = direction
            disjoint.find(identifier)

    def add_boundary(identifier: str, direction: str) -> None:
        node = by_id.get(identifier)
        if node is None:
            raise CxfArrayScalarizationError(f"missing boundary connector {identifier}")
        shape = _shape(node, root_values) if node.get("S231:isArray") is True else ()
        endpoint_shapes[identifier] = shape
        endpoint_maps[identifier] = {}
        indices = _indices(shape) if shape else [()]
        for index in indices:
            scalar = _scalar_connector(node, index) if index else copy.deepcopy(node)
            scalar.pop("S231:isConnectedTo", None)
            register(scalar, direction)
            endpoint_maps[identifier][index] = scalar["@id"]

    for identifier in input_ids:
        add_boundary(identifier, "source")
    for identifier in output_ids:
        add_boundary(identifier, "sink")

    def component_value(component_id: str, name: str) -> Any:
        node = by_id.get(f"{component_id}.{name}")
        if node is None or "S231:value" not in node:
            raise CxfArrayScalarizationError(f"{component_id}.{name} is missing")
        value = _literal(node["S231:value"])
        return root_values.get(value, value) if isinstance(value, str) else value

    def virtual(base: str, index: tuple[int, ...]) -> str:
        token = "@virtual:" + (_scalar_id(base, index) if index else base)
        disjoint.find(token)
        return token

    def dynamic_endpoint(base: str, shape: tuple[int, ...]) -> None:
        endpoint_shapes[base] = shape
        endpoint_maps[base] = {
            index: virtual(base, index) for index in (_indices(shape) if shape else [()])
        }

    reduction_count = 0
    filter_count = 0
    scalar_replicator_count = 0
    matrix_gain_count = 0
    limiter_count = 0
    expanded_component_count = 0
    inactive_endpoints: set[str] = set()
    for component, class_name in zip(components, classes, strict=True):
        assert component is not None
        component_id = str(component["@id"])
        if class_name in _SCALAR_REPLICATORS:
            nout = _component_parameter(component_id, "nout", by_id, root_values)
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, ())
            dynamic_endpoint(output_base, (nout,))
            for output_index in range(1, nout + 1):
                disjoint.union(
                    endpoint_maps[input_base][()],
                    endpoint_maps[output_base][(output_index,)],
                )
            scalar_replicator_count += 1
            continue
        if class_name == _MATRIX_GAIN:
            matrix = _parse_array_expression(
                component_value(component_id, "K"),
                root_values,
                context=f"{component_id}.K",
            )
            if not matrix or not all(isinstance(row, list) and row for row in matrix):
                raise CxfArrayScalarizationError(
                    f"{component_id}.K must be a non-empty numeric matrix"
                )
            widths = {len(row) for row in matrix}
            if len(widths) != 1:
                raise CxfArrayScalarizationError(f"{component_id}.K must be rectangular")
            nout = len(matrix)
            nin = widths.pop()
            for row in matrix:
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in row
                ):
                    raise CxfArrayScalarizationError(
                        f"{component_id}.K must contain finite numeric values"
                    )
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(output_base, (nout,))
            for row_index, row in enumerate(matrix, start=1):
                term_outputs: list[str] = []
                for column_index, coefficient in enumerate(row, start=1):
                    term_id = f"{component_id}__term_{row_index}_{column_index}"
                    constant_id = term_id + "__coefficient"
                    constant_parameter = f"{constant_id}.k"
                    constant_output = f"{constant_id}.y"
                    u1 = f"{term_id}.u1"
                    u2 = f"{term_id}.u2"
                    output = f"{term_id}.y"
                    register(
                        _component(
                            constant_id,
                            "Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
                            f"matrix coefficient {row_index},{column_index}",
                            [constant_parameter, constant_output],
                        )
                    )
                    register(
                        {
                            "@id": constant_parameter,
                            "S231:isFinal": True,
                            "S231:value": float(coefficient),
                        }
                    )
                    register(_port(constant_output), "source")
                    register(
                        _component(
                            term_id,
                            "Buildings.Controls.OBC.CDL.Reals.Multiply",
                            f"matrix term {row_index},{column_index}",
                            [u1, u2, output],
                        )
                    )
                    register(_port(u1), "sink")
                    register(_port(u2), "sink")
                    register(_port(output), "source")
                    new_component_ids.extend([constant_id, term_id])
                    disjoint.union(constant_output, u1)
                    disjoint.union(endpoint_maps[input_base][(column_index,)], u2)
                    term_outputs.append(output)
                accumulator = term_outputs[0]
                for column_index, term_output in enumerate(term_outputs[1:], start=2):
                    add_id = f"{component_id}__sum_{row_index}_{column_index}"
                    u1 = f"{add_id}.u1"
                    u2 = f"{add_id}.u2"
                    output = f"{add_id}.y"
                    register(
                        _component(
                            add_id,
                            "Buildings.Controls.OBC.CDL.Reals.Add",
                            f"matrix row {row_index} sum {column_index}",
                            [u1, u2, output],
                        )
                    )
                    register(_port(u1), "sink")
                    register(_port(u2), "sink")
                    register(_port(output), "source")
                    new_component_ids.append(add_id)
                    disjoint.union(accumulator, u1)
                    disjoint.union(term_output, u2)
                    accumulator = output
                disjoint.union(accumulator, endpoint_maps[output_base][(row_index,)])
            matrix_gain_count += 1
            continue
        if class_name == _LIMITER:
            minimum = component_value(component_id, "uMin")
            maximum = component_value(component_id, "uMax")
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, (int, float))
                or not isinstance(maximum, (int, float))
                or not math.isfinite(float(minimum))
                or not math.isfinite(float(maximum))
                or float(minimum) > float(maximum)
            ):
                raise CxfArrayScalarizationError(f"{component_id} requires finite uMin <= uMax")
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, ())
            dynamic_endpoint(output_base, ())
            min_constant = f"{component_id}__minimum"
            max_constant = f"{component_id}__maximum"
            lower = f"{component_id}__lower"
            upper = f"{component_id}__upper"
            for constant_id, value, label in (
                (min_constant, minimum, "minimum"),
                (max_constant, maximum, "maximum"),
            ):
                parameter = f"{constant_id}.k"
                output = f"{constant_id}.y"
                register(
                    _component(
                        constant_id,
                        "Buildings.Controls.OBC.CDL.Reals.Sources.Constant",
                        f"{component.get('S231:label', component_id)} {label}",
                        [parameter, output],
                    )
                )
                register({"@id": parameter, "S231:isFinal": True, "S231:value": float(value)})
                register(_port(output), "source")
                new_component_ids.append(constant_id)
            for block_id, block_class in (
                (lower, "Buildings.Controls.OBC.CDL.Reals.Max"),
                (upper, "Buildings.Controls.OBC.CDL.Reals.Min"),
            ):
                register(
                    _component(
                        block_id,
                        block_class,
                        f"{component.get('S231:label', component_id)} clamp",
                        [f"{block_id}.u1", f"{block_id}.u2", f"{block_id}.y"],
                    )
                )
                register(_port(f"{block_id}.u1"), "sink")
                register(_port(f"{block_id}.u2"), "sink")
                register(_port(f"{block_id}.y"), "source")
                new_component_ids.append(block_id)
            disjoint.union(endpoint_maps[input_base][()], f"{lower}.u1")
            disjoint.union(f"{min_constant}.y", f"{lower}.u2")
            disjoint.union(f"{lower}.y", f"{upper}.u1")
            disjoint.union(f"{max_constant}.y", f"{upper}.u2")
            disjoint.union(f"{upper}.y", endpoint_maps[output_base][()])
            limiter_count += 1
            continue
        if class_name in _VECTOR_FILTERS:
            nin = _component_parameter(component_id, "nin", by_id, root_values)
            nout = _component_parameter(component_id, "nout", by_id, root_values)
            mask = _parse_array_expression(
                component_value(component_id, "msk"),
                root_values,
                context=f"{component_id}.msk",
            )
            if len(mask) != nin or not all(isinstance(value, bool) for value in mask):
                raise CxfArrayScalarizationError(
                    f"{component_id}.msk must contain exactly {nin} Boolean values"
                )
            selected = [index for index, enabled in enumerate(mask, start=1) if enabled]
            if len(selected) != nout:
                raise CxfArrayScalarizationError(
                    f"{component_id}.msk selects {len(selected)} values but nout={nout}"
                )
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(output_base, (nout,))
            for output_index, input_index in enumerate(selected, start=1):
                disjoint.union(
                    endpoint_maps[input_base][(input_index,)],
                    endpoint_maps[output_base][(output_index,)],
                )
            filter_count += 1
            continue
        if class_name in _REDUCTIONS:
            nin = _component_parameter(component_id, "nin", by_id, root_values)
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(output_base, ())
            if nin == 1:
                disjoint.union(endpoint_maps[input_base][(1,)], endpoint_maps[output_base][()])
            else:
                previous_output: str | None = None
                for input_index in range(2, nin + 1):
                    fold_id = f"{component_id}__fold_{input_index}"
                    u1 = f"{fold_id}.u1"
                    u2 = f"{fold_id}.u2"
                    output = f"{fold_id}.y"
                    fold = _component(
                        fold_id,
                        _REDUCTIONS[class_name],
                        f"{component.get('S231:label', component_id)} fold {input_index}",
                        [u1, u2, output],
                    )
                    register(fold)
                    register(_port(u1), "sink")
                    register(_port(u2), "sink")
                    register(_port(output), "source")
                    new_component_ids.append(fold_id)
                    if previous_output is None:
                        disjoint.union(endpoint_maps[input_base][(1,)], u1)
                    else:
                        disjoint.union(previous_output, u1)
                    disjoint.union(endpoint_maps[input_base][(input_index,)], u2)
                    previous_output = output
                assert previous_output is not None
                disjoint.union(previous_output, endpoint_maps[output_base][()])
            reduction_count += 1
            continue

        schema = INSTANCE_SCHEMAS[class_name]
        active_input_slots = set(schema["inputs"])
        if class_name in PLACEHOLDER_CLASSES:
            have_input_node = by_id.get(f"{component_id}.have_inp")
            have_placeholder_node = by_id.get(f"{component_id}.have_inpPh")
            have_input = (
                resolve_parameter_expression(
                    component_value(component_id, "have_inp"), root_values
                )
                if have_input_node is not None
                else True
            )
            have_placeholder = (
                resolve_parameter_expression(
                    component_value(component_id, "have_inpPh"), root_values
                )
                if have_placeholder_node is not None
                else False
            )
            if not isinstance(have_input, bool) or not isinstance(
                have_placeholder, bool
            ):
                raise CxfArrayScalarizationError(
                    f"{component_id} placeholder availability must resolve to Boolean"
                )
            active_input_slots = (
                {"u"}
                if have_input
                else {"uPh"}
                if have_placeholder
                else set()
            )
        component_shape = (
            _shape(component, root_values) if component.get("S231:isArray") is True else ()
        )
        component_indices = _indices(component_shape) if component_shape else [()]
        for index in component_indices:
            scalar_id = _scalar_id(component_id, index) if index else component_id
            scalar = copy.deepcopy(component)
            scalar["@id"] = scalar_id
            scalar.pop("S231:isConnectedTo", None)
            for field in _ARRAY_FIELDS:
                scalar.pop(field, None)
            label = str(component.get("S231:label", component_id.rsplit(".", 1)[-1]))
            label = re.sub(r"\s*\[[^]]*\]\s*$", "", label)
            scalar["S231:label"] = (
                label + "__" + "_".join(str(item) for item in index) if index else label
            )
            child_ids: list[str] = []
            for role in ("parameters", "inputs", "outputs"):
                for slot in schema[role]:
                    if role == "inputs" and slot not in active_input_slots:
                        inactive_endpoints.add(f"{component_id}.{slot}")
                        continue
                    original_id = f"{component_id}.{slot}"
                    if role == "parameters" and original_id not in by_id:
                        # Omitted parameter instances intentionally inherit the
                        # exact CDL class default. Creating an empty node would
                        # override that default with an ungrounded value.
                        continue
                    child_id = f"{scalar_id}.{slot}"
                    child_ids.append(child_id)
                    child = copy.deepcopy(by_id.get(original_id, {"@id": original_id}))
                    child["@id"] = child_id
                    child.pop("S231:isConnectedTo", None)
                    for field in _ARRAY_FIELDS:
                        child.pop(field, None)
                    if role == "parameters" and index and "S231:value" in child:
                        raw_value = _literal(child["S231:value"])
                        resolved = (
                            root_values.get(raw_value, raw_value)
                            if isinstance(raw_value, str)
                            else raw_value
                        )
                        if isinstance(resolved, str) and (
                            resolved.strip().startswith("{") or resolved.strip().startswith("fill(")
                        ):
                            selected: Any = _parse_array_expression(
                                resolved,
                                root_values,
                                context=original_id,
                            )
                            for dimension_index in index:
                                if not isinstance(selected, list) or dimension_index > len(
                                    selected
                                ):
                                    raise CxfArrayScalarizationError(
                                        f"{original_id} does not match component shape"
                                    )
                                selected = selected[dimension_index - 1]
                            child["S231:value"] = selected
                    register(
                        child,
                        "sink" if role == "inputs" else "source" if role == "outputs" else None,
                    )
                    if role in {"inputs", "outputs"}:
                        endpoint_shapes.setdefault(original_id, component_shape)
                        endpoint_maps.setdefault(original_id, {})[index] = child_id
            _set_refs(scalar, "S231:hasInstance", child_ids)
            register(scalar)
            new_component_ids.append(scalar_id)
            expanded_component_count += 1

    for node in graph:
        source = node.get("@id")
        if not isinstance(source, str):
            continue
        source_selection = _endpoint_selection(source, endpoint_maps, endpoint_shapes)
        if source_selection is None:
            continue
        for reference in _items(node.get("S231:isConnectedTo")):
            target = reference.get("@id")
            target_selection = (
                _endpoint_selection(target, endpoint_maps, endpoint_shapes)
                if isinstance(target, str)
                else None
            )
            if target_selection is None:
                if isinstance(target, str) and target in inactive_endpoints:
                    continue
                raise CxfArrayScalarizationError(
                    f"connection from {source} references unsupported array endpoint {target}"
                )
            source_shape, source_map = source_selection
            target_shape, target_map = target_selection
            if source_shape != target_shape:
                raise CxfArrayScalarizationError(
                    f"connection shape mismatch: {source} {source_shape} to {target} {target_shape}"
                )
            indices = _indices(source_shape) if source_shape else [()]
            for index in indices:
                disjoint.union(source_map[index], target_map[index])

    connected_set_count = 0
    for members in disjoint.groups():
        actual = sorted(member for member in members if member in directions)
        if not actual:
            continue
        sources = [member for member in actual if directions[member] == "source"]
        sinks = [member for member in actual if directions[member] == "sink"]
        if not sinks:
            continue
        if len(sources) != 1:
            raise CxfArrayScalarizationError(
                "scalarized connection set must contain exactly one source: " + ", ".join(actual)
            )
        _set_refs(node_by_id[sources[0]], "S231:isConnectedTo", sinks)
        connected_set_count += 1

    scalar_root = copy.deepcopy(root)
    scalar_root.pop("S231:isConnectedTo", None)
    scalar_parameter_ids = [
        identifier
        for identifier in parameter_ids
        if by_id.get(identifier, {}).get("S231:isArray") is not True
    ]
    _set_refs(scalar_root, "S231:hasParameter", scalar_parameter_ids)
    _set_refs(
        scalar_root,
        "S231:hasInput",
        [
            endpoint_maps[identifier][index]
            for identifier in input_ids
            for index in (
                _indices(endpoint_shapes[identifier]) if endpoint_shapes[identifier] else [()]
            )
        ],
    )
    _set_refs(
        scalar_root,
        "S231:hasOutput",
        [
            endpoint_maps[identifier][index]
            for identifier in output_ids
            for index in (
                _indices(endpoint_shapes[identifier]) if endpoint_shapes[identifier] else [()]
            )
        ],
    )
    _set_refs(scalar_root, "S231:containsBlock", new_component_ids)
    parameter_nodes = [copy.deepcopy(by_id[identifier]) for identifier in scalar_parameter_ids]
    result = copy.deepcopy(document)
    result["@graph"] = [scalar_root, *parameter_nodes, *generated_nodes]
    return result, {
        "schema": "bactalk.cxf-array-scalarization/v1",
        "applied": True,
        "constructs": [
            "fixed component arrays",
            "Boolean/RealVectorFilter",
            "MultiAnd/MultiOr/MultiSum/MultiMin/MultiMax",
            "Boolean/RealScalarReplicator",
            "MatrixGain",
            "Limiter",
        ],
        "source_component_count": len(components),
        "expanded_regular_component_count": expanded_component_count,
        "vector_filter_count": filter_count,
        "reduction_count": reduction_count,
        "scalar_replicator_count": scalar_replicator_count,
        "matrix_gain_count": matrix_gain_count,
        "limiter_count": limiter_count,
        "scalar_connector_count": sum(
            len(endpoint_maps[identifier]) for identifier in [*input_ids, *output_ids]
        ),
        "scalar_component_count": len(new_component_ids),
        "connected_set_count": connected_set_count,
        "policy": (
            "Grounded fixed arrays are expanded elementwise; routing blocks become explicit "
            "scalar signal sets; reductions and matrix multiplication become deterministic "
            "binary folds; limiters become bounded min/max networks; unknown dimensions, "
            "values, classes, or connection shapes fail closed."
        ),
    }


def scalarize_fixed_arrays(
    document: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Expand a reviewed subset of grounded CDL fixed-array semantics.

    The first admitted construct is the Boolean/Real VectorReplicator used by
    G36 ZoneStatusDuplicator. Each public array connector becomes an indexed
    scalar connector. Each replicated output gets an explicit scalar identity
    block, which keeps the result ordinary CXF and independently executable in
    OCE. Any mixed or unrecognized array structure remains untouched so the
    downstream validator continues to fail closed.
    """

    filter_reduction = _scalarize_filter_reduction_network(document)
    if filter_reduction is not None:
        return filter_reduction

    normalized = copy.deepcopy(document)
    raw_graph = normalized.get("@graph")
    if not isinstance(raw_graph, list):
        raise CxfArrayScalarizationError("CXF document is missing its JSON-LD graph")
    graph = [node for node in raw_graph if isinstance(node, dict)]
    array_nodes = [node for node in graph if node.get("S231:isArray") is True]
    if not array_nodes:
        return normalized, {
            "schema": "bactalk.cxf-array-scalarization/v1",
            "applied": False,
            "constructs": [],
            "scalar_connector_count": 0,
            "scalar_component_count": 0,
        }

    roots = [node for node in graph if node.get("S231:containsBlock")]
    if len(roots) != 1:
        return normalized, {
            "schema": "bactalk.cxf-array-scalarization/v1",
            "applied": False,
            "constructs": [],
            "scalar_connector_count": 0,
            "scalar_component_count": 0,
            "blocker": "array document does not have exactly one composite root",
        }
    root = roots[0]
    by_id = {node["@id"]: node for node in graph if isinstance(node.get("@id"), str)}
    components = [by_id.get(identifier) for identifier in _refs(root, "S231:containsBlock")]
    classes = [_class_name(component or {}) for component in components]
    if not components or any(class_name not in _VECTOR_REPLICATORS for class_name in classes):
        return normalized, {
            "schema": "bactalk.cxf-array-scalarization/v1",
            "applied": False,
            "constructs": [],
            "scalar_connector_count": 0,
            "scalar_component_count": 0,
            "blocker": (
                "fixed arrays include constructs outside the reviewed vector-replicator subset"
            ),
        }

    input_ids = _refs(root, "S231:hasInput")
    output_ids = _refs(root, "S231:hasOutput")
    if not input_ids or not output_ids:
        raise CxfArrayScalarizationError("vector-replicator composite requires public I/O")
    if any(by_id.get(identifier, {}).get("S231:isArray") is not True for identifier in input_ids):
        raise CxfArrayScalarizationError("all vector-replicator inputs must be fixed arrays")
    if any(by_id.get(identifier, {}).get("S231:isArray") is not True for identifier in output_ids):
        raise CxfArrayScalarizationError("all vector-replicator outputs must be fixed arrays")

    root_values = _root_parameters(root, by_id)
    membership = _connected_components(graph)
    input_shapes = {identifier: _shape(by_id[identifier], root_values) for identifier in input_ids}
    output_shapes = {
        identifier: _shape(by_id[identifier], root_values) for identifier in output_ids
    }
    scalar_inputs: dict[str, dict[tuple[int, ...], str]] = {}
    scalar_outputs: dict[str, dict[tuple[int, ...], str]] = {}
    generated: list[dict[str, Any]] = []
    for identifier, shape in input_shapes.items():
        scalar_inputs[identifier] = {}
        for index in _indices(shape):
            connector = _scalar_connector(by_id[identifier], index)
            generated.append(connector)
            scalar_inputs[identifier][index] = connector["@id"]
    for identifier, shape in output_shapes.items():
        scalar_outputs[identifier] = {}
        for index in _indices(shape):
            connector = _scalar_connector(by_id[identifier], index)
            generated.append(connector)
            scalar_outputs[identifier][index] = connector["@id"]

    new_component_ids: list[str] = []
    expansion_records: list[dict[str, Any]] = []
    for component, class_name in zip(components, classes, strict=True):
        assert component is not None
        component_id = str(component["@id"])
        input_set = membership.get(f"{component_id}.u", {f"{component_id}.u"})
        output_set = membership.get(f"{component_id}.y", {f"{component_id}.y"})
        source_candidates = sorted(set(input_ids).intersection(input_set))
        target_candidates = sorted(set(output_ids).intersection(output_set))
        if len(source_candidates) != 1 or len(target_candidates) != 1:
            raise CxfArrayScalarizationError(
                f"{component_id} must connect exactly one public input to one public output"
            )
        source_id = source_candidates[0]
        target_id = target_candidates[0]
        nin = _component_parameter(component_id, "nin", by_id, root_values)
        nout = _component_parameter(component_id, "nout", by_id, root_values)
        if input_shapes[source_id] != (nin,) or output_shapes[target_id] != (nout, nin):
            raise CxfArrayScalarizationError(
                f"{component_id} connector shapes do not match nin={nin}, nout={nout}"
            )
        data_type = _VECTOR_REPLICATORS[class_name]
        produced = 0
        for row in range(1, nout + 1):
            for column in range(1, nin + 1):
                suffix = f"__{row}_{column}"
                identity_id = component_id + suffix
                label = str(component.get("S231:label", component_id.rsplit(".", 1)[-1])) + suffix
                source_connector = scalar_inputs[source_id][(column,)]
                target_connector = scalar_outputs[target_id][(row, column)]
                if data_type == "real":
                    parameter_id = f"{identity_id}.p"
                    input_port = f"{identity_id}.u"
                    output_port = f"{identity_id}.y"
                    generated.extend(
                        [
                            _component(
                                identity_id,
                                "Buildings.Controls.OBC.CDL.Reals.AddParameter",
                                label,
                                [parameter_id, input_port, output_port],
                            ),
                            {"@id": parameter_id, "S231:isFinal": True, "S231:value": 0.0},
                            _port(input_port),
                            _port(output_port, [target_connector]),
                        ]
                    )
                    generated_by_id = {node["@id"]: node for node in generated if "@id" in node}
                    _set_refs(
                        generated_by_id[source_connector],
                        "S231:isConnectedTo",
                        _refs(generated_by_id[source_connector], "S231:isConnectedTo")
                        + [input_port],
                    )
                    new_component_ids.append(identity_id)
                else:
                    constant_id = identity_id + "__true"
                    constant_parameter = f"{constant_id}.k"
                    constant_output = f"{constant_id}.y"
                    input_one = f"{identity_id}.u1"
                    input_two = f"{identity_id}.u2"
                    output_port = f"{identity_id}.y"
                    generated.extend(
                        [
                            _component(
                                identity_id,
                                "Buildings.Controls.OBC.CDL.Logical.And",
                                label,
                                [input_one, input_two, output_port],
                            ),
                            _port(input_one),
                            _port(input_two),
                            _port(output_port, [target_connector]),
                            _component(
                                constant_id,
                                "Buildings.Controls.OBC.CDL.Logical.Sources.Constant",
                                label + " true",
                                [constant_parameter, constant_output],
                            ),
                            {
                                "@id": constant_parameter,
                                "S231:isFinal": True,
                                "S231:value": True,
                            },
                            _port(constant_output, [input_two]),
                        ]
                    )
                    generated_by_id = {node["@id"]: node for node in generated if "@id" in node}
                    _set_refs(
                        generated_by_id[source_connector],
                        "S231:isConnectedTo",
                        _refs(generated_by_id[source_connector], "S231:isConnectedTo")
                        + [input_one],
                    )
                    new_component_ids.extend([constant_id, identity_id])
                produced += 1
        expansion_records.append(
            {
                "component": component_id,
                "class": class_name,
                "input": source_id,
                "output": target_id,
                "nin": nin,
                "nout": nout,
                "scalar_identity_count": produced,
            }
        )

    removed_roots = set(input_ids + output_ids + [str(item["@id"]) for item in components if item])
    removed_prefixes = tuple(identifier + "." for identifier in removed_roots)
    retained = [
        node
        for node in graph
        if not (
            isinstance(node.get("@id"), str)
            and (node["@id"] in removed_roots or node["@id"].startswith(removed_prefixes))
        )
    ]
    for node in retained:
        node.pop("S231:isConnectedTo", None)
    retained_root = next(node for node in retained if node.get("@id") == root.get("@id"))
    _set_refs(
        retained_root,
        "S231:hasInput",
        [
            scalar_inputs[identifier][index]
            for identifier in input_ids
            for index in _indices(input_shapes[identifier])
        ],
    )
    _set_refs(
        retained_root,
        "S231:hasOutput",
        [
            scalar_outputs[identifier][index]
            for identifier in output_ids
            for index in _indices(output_shapes[identifier])
        ],
    )
    _set_refs(retained_root, "S231:containsBlock", new_component_ids)
    normalized["@graph"] = retained + generated
    return normalized, {
        "schema": "bactalk.cxf-array-scalarization/v1",
        "applied": True,
        "constructs": ["BooleanVectorReplicator", "RealVectorReplicator"],
        "source_component_count": len(components),
        "scalar_connector_count": sum(
            len(values) for values in [*scalar_inputs.values(), *scalar_outputs.values()]
        ),
        "scalar_component_count": len(new_component_ids),
        "expansions": expansion_records,
        "policy": (
            "Only fixed, grounded vector-replicator composites whose public connector shapes "
            "exactly match nin/nout are expanded; all other array constructs remain fail-closed."
        ),
    }
