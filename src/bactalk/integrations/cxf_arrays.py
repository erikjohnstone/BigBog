from __future__ import annotations

import ast
import copy
import json
import math
import re
from collections import defaultdict
from collections.abc import Callable
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
    "Buildings.Controls.OBC.CDL.Routing.IntegerVectorReplicator": "integer",
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
    "Buildings.Controls.OBC.CDL.Routing.IntegerScalarReplicator",
    "Buildings.Controls.OBC.CDL.Routing.RealScalarReplicator",
}
_MATRIX_REDUCTIONS = {
    "Buildings.Controls.OBC.CDL.Reals.MatrixMax": "Buildings.Controls.OBC.CDL.Reals.Max",
    "Buildings.Controls.OBC.CDL.Reals.MatrixMin": "Buildings.Controls.OBC.CDL.Reals.Min",
}
_SORT = "Buildings.Controls.OBC.CDL.Reals.Sort"
# y = u[min(nin, max(1, index))] with ``index`` an input: a chain of switches, each
# selecting element k when index <= k (Integers.LessThreshold with t = k + 1).
_EXTRACTORS = {
    "Buildings.Controls.OBC.CDL.Routing.RealExtractor": "Buildings.Controls.OBC.CDL.Reals.Switch",
    "Buildings.Controls.OBC.CDL.Routing.BooleanExtractor": (
        "Buildings.Controls.OBC.CDL.Logical.Switch"
    ),
    "Buildings.Controls.OBC.CDL.Routing.IntegerExtractor": (
        "Buildings.Controls.OBC.CDL.Integers.Switch"
    ),
}
# CDL time tables have a vector output sized by the table, which the engine's CXF subset
# cannot hold inside a composite. A column that holds one value in every row is that
# value at every time (the table's row selection never matters), so it becomes a scalar
# constant; a time-varying column is refused with that reason (decision 016).
_TIME_TABLES = {
    "Buildings.Controls.OBC.CDL.Logical.Sources.TimeTable": (
        "Buildings.Controls.OBC.CDL.Logical.Sources.Constant"
    ),
    "Buildings.Controls.OBC.CDL.Integers.Sources.TimeTable": (
        "Buildings.Controls.OBC.CDL.Integers.Sources.Constant"
    ),
    "Buildings.Controls.OBC.CDL.Reals.Sources.TimeTable": (
        "Buildings.Controls.OBC.CDL.Reals.Sources.Constant"
    ),
}
# The engine's table value for Integer and Boolean tables: floor(v + CDL small).
_TIME_TABLE_SMALL = 1.0e-37
# y[i] = u[extract[i]]: pure routing, one wire per output element.
_EXTRACT_SIGNALS = {
    "Buildings.Controls.OBC.CDL.Routing.BooleanExtractSignal",
    "Buildings.Controls.OBC.CDL.Routing.IntegerExtractSignal",
    "Buildings.Controls.OBC.CDL.Routing.RealExtractSignal",
}
_MATRIX_GAIN = "Buildings.Controls.OBC.CDL.Reals.MatrixGain"
_LIMITER = "Buildings.Controls.OBC.CDL.Reals.Limiter"
_ARRAY_FIELDS = ("S231:isArray", "S231:numberDimensions", "S231:sizeOfDimensions")


ENGINE_ENUM_PACKAGES = (
    "Buildings.Controls.OBC.ASHRAE.G36.Types.",
    "Buildings.Controls.OBC.CDL.Types.",
)
"""Enumeration packages the Open Control Engine grounds itself (its ``ground.rs``);
BACTalk grounds or strips only enumerations outside them, so a document the engine
already reads is left exactly as it was."""

_ENUM_LITERAL = re.compile(
    r"(?:[A-Za-z_][A-Za-z0-9_]*\.)+Types\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*"
)


class CxfArrayScalarizationError(ValueError):
    """Raised when a reviewed array construct cannot be expanded exactly."""


ChildPort = tuple[str, tuple[int, ...], str | None]
"""One port of a child composite as its parent sees it: the direction inside the
parent (``sink`` for the child's input, ``source`` for its output), the grounded
shape (``()`` for a scalar) and the port's CXF type."""

ChildPortOracle = Callable[
    [dict[str, Any], dict[str, dict[str, Any]], dict[str, int | float | bool | str]],
    dict[str, ChildPort] | None,
]
"""Answers, for a component whose class is a separately emitted composite, the ports
its class declares (keyed by the instance-prefixed port id) under the instance's
parameter bindings; ``None`` for anything that is not such a composite. The array
scalariser uses it to treat a child composite as an opaque block whose array ports
split into the same ``port__i`` connectors the child's own scalarisation produces."""


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
    return _grounded_booleans(values)


def _grounded_booleans(
    values: dict[str, int | float | bool | str],
) -> dict[str, int | float | bool | str]:
    """Ground derived Boolean parameters (``have_pumChiWatPri=have_chiWat and (...)``).

    Only expressions that resolve to a Boolean are replaced, so numeric parameters keep
    the literal form the rest of the pipeline reads.
    """

    grounded = dict(values)
    for _ in range(max(1, len(grounded))):
        changed = False
        for name, value in list(grounded.items()):
            if not isinstance(value, str):
                continue
            resolved = resolve_parameter_expression(value, grounded)
            if isinstance(resolved, bool):
                grounded[name] = resolved
                changed = True
        if not changed:
            break
    return grounded


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


def _dimension_tokens(raw: str) -> list[str] | None:
    """The top-level, comma-separated dimension expressions of ``(d1, d2, ...)``."""

    text = raw.strip()
    if not text.startswith("(") or not text.endswith(")"):
        # modelica-json writes a single expression dimension without its parentheses
        # (``phPumChiWatPriSta[if have_pumChiWatPri then nPumChiWatPri else ...]``)
        if not text or any(character in text for character in ",()[]{}"):
            return None
        return [text]
    tokens: list[str] = []
    depth = 0
    current = ""
    for character in text[1:-1]:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        if character == "," and depth == 0:
            tokens.append(current.strip())
            current = ""
            continue
        current += character
    tokens.append(current.strip())
    if depth != 0 or any(not token for token in tokens):
        return None
    return tokens


def _shape(
    node: dict[str, Any],
    values: dict[str, int | float | bool | str],
) -> tuple[int, ...]:
    identifier = str(node.get("@id", "array"))
    raw = node.get("S231:sizeOfDimensions")
    tokens = _dimension_tokens(raw) if isinstance(raw, str) else None
    if tokens is None:
        raise CxfArrayScalarizationError(
            f"{identifier} has an unsupported fixed-array dimension declaration"
        )
    dimensions = tuple(
        _resolve_dimension(
            token
            if re.fullmatch(r"[A-Za-z0-9_]+", token)
            # ``[if have_pumChiWatPri then nPumChiWatPri else nPumHeaWatPri]``
            else resolve_parameter_expression(token, values),
            values,
            context=f"{identifier} dimension {token}",
        )
        for token in tokens
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
    shape = endpoint_shapes[base]
    if len(index) < len(shape):
        # ``inst[2].y`` (written ``inst.y[2]``) on an array of instances whose ``y`` is
        # itself a vector: the leading index picks the instance, the rest stays whole.
        if any(not 1 <= position <= size for position, size in zip(index, shape, strict=False)):
            raise CxfArrayScalarizationError(
                f"array endpoint {identifier} is outside declared shape {shape}"
            )
        remaining = shape[len(index) :]
        return remaining, {
            key[len(index) :]: target
            for key, target in endpoint_maps[base].items()
            if key[: len(index)] == index
        }
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


def _python_conditional(text: str) -> str:
    """Rewrite Modelica ``if c then a else b`` (chains included) as Python's
    ``(a) if (c) else (b)`` so :mod:`ast` can read it; ``<>`` becomes ``!=``."""

    tokens = re.split(r"(\bif\b|\bthen\b|\belse\b)", text.replace("<>", "!="))
    if "if" not in tokens:
        return text.replace("<>", "!=")
    position = 0

    def parse() -> str:
        nonlocal position
        pieces: list[str] = []
        while position < len(tokens):
            token = tokens[position]
            if token == "if":
                position += 1
                condition = parse_until("then")
                body = parse_until("else")
                alternative = parse()
                return "".join(pieces) + f"(({body}) if ({condition}) else ({alternative}))"
            if token in {"then", "else"}:
                break
            pieces.append(token)
            position += 1
        return "".join(pieces)

    def parse_until(keyword: str) -> str:
        nonlocal position
        piece = parse()
        if position >= len(tokens) or tokens[position] != keyword:
            raise CxfArrayScalarizationError(f"malformed Modelica if-expression: {text!r}")
        position += 1
        return piece

    return parse()


def _parse_array_expression(
    expression: Any,
    root_values: dict[str, Any],
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

    local: dict[str, int | float | bool | str] = {}

    def evaluate(node: ast.AST, text: str) -> int | float | bool | str:
        if isinstance(node, ast.Expression):
            return evaluate(node.body, text)
        if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id.lower() in {"true", "false"}:
                return node.id.lower() == "true"
            resolved = local.get(node.id, root_values.get(node.id))
            if isinstance(resolved, str) and _ENUM_LITERAL.fullmatch(resolved):
                return resolved
            if isinstance(resolved, bool):
                return resolved  # arithmetic below still refuses Booleans
            if not isinstance(resolved, (int, float)):
                raise CxfArrayScalarizationError(f"{context} contains ungrounded name {node.id}")
            return resolved
        if isinstance(node, ast.Attribute):
            # an enumeration literal (``...Types.ChillersAndStages.PositiveDisplacement``)
            parts: list[str] = []
            current: ast.AST = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                name = ".".join([current.id, *reversed(parts)])
                if _ENUM_LITERAL.fullmatch(name):
                    return name
            raise CxfArrayScalarizationError(f"{context} contains an unsupported name")
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and isinstance(root_values.get(node.value.id), list)
        ):
            # ``chiTyp[i]`` inside a comprehension: one-based element of a grounded
            # array parameter; ``staEqu[i, j]`` indexes a matrix.
            values = root_values[node.value.id]
            if isinstance(node.slice, ast.Tuple):
                *leading, last = node.slice.elts
                for axis in leading:
                    row = evaluate(axis, text)
                    if (
                        isinstance(row, bool)
                        or not isinstance(row, (int, float))
                        or not float(row).is_integer()
                        or not 1 <= int(row) <= len(values)
                        or not isinstance(values[int(row) - 1], list)
                    ):
                        raise CxfArrayScalarizationError(f"{context} indexes outside an array")
                    values = values[int(row) - 1]
                position = evaluate(last, text)
            else:
                position = evaluate(node.slice, text)
            if (
                isinstance(position, bool)
                or not isinstance(position, (int, float))
                or not float(position).is_integer()
                or not 1 <= int(position) <= len(values)
            ):
                raise CxfArrayScalarizationError(f"{context} indexes outside an array")
            element = _literal(values[int(position) - 1])
            if isinstance(element, (bool, int, float)) or (
                isinstance(element, str) and _ENUM_LITERAL.fullmatch(element)
            ):
                return element
            raise CxfArrayScalarizationError(f"{context} indexes a non-scalar element")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"min", "max"}
            and not node.keywords
            and node.args
        ):
            if len(node.args) == 1:
                operands = _flatten(evaluate_array(node.args[0], text))
            else:
                operands = [evaluate(argument, text) for argument in node.args]
            if not operands or any(isinstance(item, (bool, str)) for item in operands):
                raise CxfArrayScalarizationError(f"{context} takes {node.func.id} of non-numbers")
            return min(operands) if node.func.id == "min" else max(operands)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"sum", "size"}
            and not node.keywords
        ):
            array = evaluate_array(node.args[0], text) if node.args else None
            if node.func.id == "sum" and len(node.args) == 1 and array is not None:
                flat = _flatten(array)
                if any(isinstance(item, (bool, str)) for item in flat):
                    raise CxfArrayScalarizationError(f"{context} sums non-numeric values")
                return sum(flat)
            if node.func.id == "size" and len(node.args) == 2 and array is not None:
                dimension = evaluate(node.args[1], text)
                current: Any = array
                for _ in range(int(dimension) - 1):  # type: ignore[arg-type]
                    current = current[0] if isinstance(current, list) and current else None
                if not isinstance(current, list):
                    raise CxfArrayScalarizationError(f"{context} asks size of a missing dimension")
                return len(current)
            raise CxfArrayScalarizationError(f"{context} has an unsupported {node.func.id}()")
        if isinstance(node, ast.IfExp):
            condition = evaluate(node.test, text)
            if not isinstance(condition, bool):
                raise CxfArrayScalarizationError(f"{context} has a non-Boolean condition")
            return evaluate(node.body if condition else node.orelse, text)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left = evaluate(node.left, text)
            right = evaluate(node.comparators[0], text)
            operator = node.ops[0]
            if isinstance(operator, ast.Eq):
                return left == right
            if isinstance(operator, ast.NotEq):
                return left != right
            if isinstance(left, (str, bool)) or isinstance(right, (str, bool)):
                raise CxfArrayScalarizationError(f"{context} orders non-numeric values")
            if isinstance(operator, ast.Lt):
                return left < right
            if isinstance(operator, ast.LtE):
                return left <= right
            if isinstance(operator, ast.Gt):
                return left > right
            if isinstance(operator, ast.GtE):
                return left >= right
        if isinstance(node, ast.BoolOp):
            values = [evaluate(value, text) for value in node.values]
            if not all(isinstance(value, bool) for value in values):
                raise CxfArrayScalarizationError(f"{context} combines non-Boolean values")
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operand = evaluate(node.operand, text)
            if not isinstance(operand, bool):
                raise CxfArrayScalarizationError(f"{context} negates a non-Boolean value")
            return not operand
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = evaluate(node.operand, text)
            if isinstance(operand, (bool, str)):
                raise CxfArrayScalarizationError(f"{context} uses non-numeric arithmetic")
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left = evaluate(node.left, text)
            right = evaluate(node.right, text)
            if isinstance(left, (bool, str)) or isinstance(right, (bool, str)):
                raise CxfArrayScalarizationError(f"{context} uses non-numeric arithmetic")
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise CxfArrayScalarizationError(
            f"{context} contains unsupported scalar expression {text!r}"
        )

    def evaluate_array(node: ast.AST, text: str) -> list[Any]:
        """An array operand: a grounded array, one row (``X[i,:]`` or ``X[i]``) or one
        column (``X[:,j]``) of a grounded matrix."""

        if isinstance(node, ast.Name) and isinstance(root_values.get(node.id), list):
            return list(root_values[node.id])
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and isinstance(root_values.get(node.value.id), list)
        ):
            matrix = root_values[node.value.id]
            parts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]

            def position(part: ast.AST) -> int:
                value = evaluate(part, text)
                if isinstance(value, bool) or not float(value).is_integer():  # type: ignore[arg-type]
                    raise CxfArrayScalarizationError(f"{context} has a non-integer index")
                return int(value)  # type: ignore[arg-type]

            if len(parts) == 1 and not isinstance(parts[0], ast.Slice):
                row = matrix[position(parts[0]) - 1]
                if isinstance(row, list):
                    return list(row)
            if (
                len(parts) == 2
                and isinstance(parts[1], ast.Slice)
                and not isinstance(parts[0], ast.Slice)
            ):
                row = matrix[position(parts[0]) - 1]
                if isinstance(row, list):
                    return list(row)
            if (
                len(parts) == 2
                and isinstance(parts[0], ast.Slice)
                and not isinstance(parts[1], ast.Slice)
            ):
                column = position(parts[1])
                return [row[column - 1] for row in matrix if isinstance(row, list)]
        if isinstance(node, ast.List):
            return [evaluate(item, text) for item in node.elts]
        raise CxfArrayScalarizationError(f"{context} has an unsupported array operand")

    def evaluate_scalar(value: str) -> int | float | bool | str:
        # An enumeration literal (``fill(controllerType, nSen)`` with controllerType a
        # ``...Types.SimpleController`` member) is carried through as its name; the
        # component that receives it grounds it like any scalar enum parameter.
        literal = root_values.get(value.strip(), value.strip())
        if isinstance(literal, str) and _ENUM_LITERAL.fullmatch(literal):
            return literal
        text = _python_conditional(value)
        try:
            parsed = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            raise CxfArrayScalarizationError(
                f"{context} contains an invalid scalar expression"
            ) from exc
        result = evaluate(parsed, value)
        if isinstance(result, float) and not math.isfinite(result):
            raise CxfArrayScalarizationError(f"{context} contains a non-finite value")
        return result

    fill = re.fullmatch(r"fill\(\s*(.+?)\s*((?:,\s*[A-Za-z0-9_]+\s*)+)\)", stripped)
    if fill is not None:
        counts = [
            _resolve_dimension(token.strip(), root_values, context=f"{context} fill count")
            for token in fill.group(2).split(",")[1:]
        ]
        filled: Any = evaluate_scalar(fill.group(1))
        for count in reversed(counts):
            filled = [copy.deepcopy(filled) for _ in range(count)]
        return filled
    comprehension = re.fullmatch(
        r"\{\s*(.+?)\s+for\s+((?:[A-Za-z_][A-Za-z0-9_]*\s+in\s+[A-Za-z0-9_]+\s*:\s*"
        r"[A-Za-z0-9_]+\s*,?\s*)+)\}",
        stripped,
    )
    if comprehension is not None and not re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*)\s+for\s+\1\s+in\s+1\s*:\s*[A-Za-z0-9_]+\s*",
        stripped[1:-1].strip(),
    ):
        # ``{e for i in a:b, j in c:d}`` is ``{{e for i in a:b} for j in c:d}``: the last
        # iterator is the outermost dimension (Modelica 10.4.1.1).
        iterators = [
            (
                match.group(1),
                _resolve_dimension(match.group(2), root_values, context=f"{context} bound"),
                _resolve_dimension(match.group(3), root_values, context=f"{context} bound"),
            )
            for match in re.finditer(
                r"([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z0-9_]+)\s*:\s*([A-Za-z0-9_]+)",
                comprehension.group(2),
            )
        ]

        body = comprehension.group(1).strip()

        def element() -> Any:
            # ``{idxEquAlt for i in 1:n}``: a grounded array body repeats as a row.
            if isinstance(root_values.get(body), list) and body not in local:
                return copy.deepcopy(root_values[body])
            if body.startswith("{") and body.endswith("}"):
                # a nested comprehension (``{{staEqu[i, j] for i in 1:nSta} for j in
                # 1:nEqu}``) sees the outer iterators as grounded names
                return _parse_array_expression(body, {**root_values, **local}, context=context)
            return evaluate_scalar(body)

        def build(depth: int) -> Any:
            name, low, high = iterators[depth]
            values: list[Any] = []
            for current in range(low, high + 1):
                local[name] = current
                values.append(element() if depth == 0 else build(depth - 1))
            local.pop(name, None)
            return values

        return build(len(iterators) - 1)
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
    if stripped.startswith("[") and stripped.endswith("]"):
        # Modelica matrix construction ``[0, 1; 24*3600, 1]``: rows by ``;``
        def split_top(text: str, separator: str) -> list[str]:
            parts: list[str] = []
            depth = 0
            current = ""
            for character in text:
                if character in "([{":
                    depth += 1
                elif character in ")]}":
                    depth -= 1
                if character == separator and depth == 0:
                    parts.append(current)
                    current = ""
                    continue
                current += character
            parts.append(current)
            return [part.strip() for part in parts]

        matrix = [
            [evaluate_scalar(element) for element in split_top(row, ",")]
            for row in split_top(stripped[1:-1], ";")
        ]
        if not matrix or any(not row or "" in row for row in matrix):
            raise CxfArrayScalarizationError(f"{context} is not a literal matrix")
        return matrix
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise CxfArrayScalarizationError(
            f"{context} uses an unsupported array expression {expression!r}"
        )
    as_json = stripped.replace("{", "[").replace("}", "]")
    try:
        parsed = json.loads(as_json)
    except json.JSONDecodeError:
        # Elements that are names or expressions (``{Types.X.A, Types.X.B}``): read the
        # nesting with Python's parser and evaluate each element.
        try:
            tree = ast.parse(as_json, mode="eval").body
        except SyntaxError as exc:
            raise CxfArrayScalarizationError(
                f"{context} is not a literal rectangular array"
            ) from exc

        def elements(node: ast.AST) -> Any:
            if isinstance(node, ast.List):
                return [elements(item) for item in node.elts]
            return evaluate(node, stripped)

        parsed = elements(tree)
    if not isinstance(parsed, list):
        raise CxfArrayScalarizationError(f"{context} is not an array")
    return parsed


def _element_expression(
    value: Any,
    index: tuple[int, ...],
    root_array_values: dict[str, Any],
    *,
    context: str,
) -> Any:
    """The modification one element of a component array receives.

    LBNL writes an instance array's modifications as ``fill(expr, n)``, a brace literal,
    or the name of an array parameter; Modelica hands element ``i`` to instance ``i``.
    ``fill`` keeps ``expr`` as an expression for the assembler to ground in the parent
    scope, so nothing is evaluated here. A scalar modification applies to every element,
    which is Modelica's ``each``.
    """

    raw = _literal(value)
    for _ in range(4):
        if isinstance(raw, str) and raw.strip() in root_array_values:
            raw = _literal(root_array_values[raw.strip()])
        else:
            break
    if isinstance(raw, list):
        selected: Any = raw
        for position in index:
            if not isinstance(selected, list) or position > len(selected):
                raise CxfArrayScalarizationError(f"{context} does not match the instance array")
            selected = selected[position - 1]
        return selected
    if not isinstance(raw, str):
        return raw
    stripped = raw.strip()
    fill = re.fullmatch(r"fill\(\s*(.+?)\s*((?:,\s*[A-Za-z0-9_]+\s*)+)\)", stripped)
    if fill is not None:
        dimensions = [token.strip() for token in fill.group(2).split(",")[1:]]
        if len(index) > len(dimensions):
            raise CxfArrayScalarizationError(f"{context} has fewer dimensions than the array")
        remaining = dimensions[len(index) :]
        return (
            fill.group(1)
            if not remaining
            else "fill(" + fill.group(1) + ", " + ", ".join(remaining) + ")"
        )
    if stripped.startswith("{") and stripped.endswith("}"):
        converted = stripped.replace("{", "[").replace("}", "]")
        try:
            tree = ast.parse(converted, mode="eval").body
        except SyntaxError as exc:
            raise CxfArrayScalarizationError(f"{context} is not a readable array") from exc
        for position in index:
            if not isinstance(tree, ast.List) or position > len(tree.elts):
                raise CxfArrayScalarizationError(f"{context} does not match the instance array")
            tree = tree.elts[position - 1]
        segment = ast.get_source_segment(converted, tree)
        if segment is None:
            raise CxfArrayScalarizationError(f"{context} element could not be read")
        element = segment.replace("[", "{").replace("]", "}")
        literal = _literal(element)
        try:
            return json.loads(element.lower() if element in {"true", "false"} else element)
        except (json.JSONDecodeError, ValueError):
            return literal
    return raw


def _flatten(values: Any) -> list[Any]:
    if not isinstance(values, list):
        return [values]
    flat: list[Any] = []
    for item in values:
        flat.extend(_flatten(item))
    return flat


def _grounded_array_parameters(
    root: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    root_values: dict[str, Any],
) -> dict[str, Any]:
    """A composite's array parameters, grounded to literal arrays in its own scope.

    Their expressions name this composite's parameters, which a child that receives the
    value cannot see. One array may be built from another (``chiTypMat`` from
    ``chiTypInt``), so this repeats until nothing more grounds; an array that does not
    ground keeps its expression.
    """

    values: dict[str, Any] = {}
    declarations = [
        identifier
        for identifier in _refs(root, "S231:hasParameter")
        if by_id.get(identifier, {}).get("S231:isArray") is True
        and "S231:value" in by_id[identifier]
    ]
    for _ in range(len(declarations) + 1):
        progressed = False
        for identifier in declarations:
            name = identifier.rsplit(".", 1)[-1]
            if isinstance(values.get(name), list):
                continue
            try:
                values[name] = _parse_array_expression(
                    by_id[identifier]["S231:value"],
                    {**root_values, **values},
                    context=identifier,
                )
                progressed = True
            except CxfArrayScalarizationError:
                values[name] = by_id[identifier]["S231:value"]
        if not progressed:
            break
    return values


def _evaluate_parameter_text(text: str, scope: dict[str, Any], *, context: str) -> Any:
    """Evaluate one scalar parameter expression that reads arrays.

    ``sum(<array expression>)`` becomes its total, then the remainder is read by the
    array evaluator's scalar grammar (Modelica if-expressions, comparisons, Boolean
    operators, enumeration literals, one-based indexing into grounded arrays).
    """

    rewritten = text
    for _ in range(16):
        start = rewritten.find("sum(")
        if start < 0:
            break
        depth = 0
        end = -1
        for position in range(start + 3, len(rewritten)):
            if rewritten[position] == "(":
                depth += 1
            elif rewritten[position] == ")":
                depth -= 1
                if depth == 0:
                    end = position
                    break
        if end < 0:
            raise CxfArrayScalarizationError(f"{context} has an unbalanced sum(")
        values = _parse_array_expression(rewritten[start + 4 : end], scope, context=context)
        flat: list[Any] = []
        stack: list[Any] = [values]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            else:
                flat.append(item)
        if any(isinstance(item, (bool, str)) for item in flat):
            raise CxfArrayScalarizationError(f"{context} sums non-numeric values")
        rewritten = rewritten[:start] + repr(sum(flat)) + rewritten[end + 1 :]
    # a one-element comprehension reuses the evaluator's scalar grammar
    return _parse_array_expression(
        "{" + rewritten + " for bactalk_scalar in 1:1}", scope, context=context
    )[0]


def ground_array_derived_parameters(graph: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ground values whose expressions read an array or an enumeration parameter.

    ``final parameter Boolean anyVsdCen = sum({if chiTyp[i] == ...VariableSpeedCentrifugal
    then 1 else 0 for i in 1:nChi}) > 0``, ``conInt2(k=size(staMat, 2))`` and
    ``con3(k=not (have_modPosChiVal and chiIsoValTyp == ...TwoPosition))`` read arrays
    or enumeration literals, which neither the guard resolver nor the engine can
    evaluate (the engine also refuses array parameters on a composite). Both this
    composite's scalar parameters and its components' parameter values are grounded,
    but only expressions that name such a parameter (or build an array) are touched,
    so a declaration the engine could already read never changes; one that does not
    ground is left as it is.
    """

    roots = [node for node in graph if node.get("S231:containsBlock")]
    if len(roots) != 1:
        return []
    root = roots[0]
    by_id = {node["@id"]: node for node in graph if isinstance(node.get("@id"), str)}
    root_values: dict[str, Any] = dict(_root_parameters(root, by_id))
    arrays = _grounded_array_parameters(root, by_id, root_values)
    special = {name for name, value in arrays.items() if isinstance(value, list)} | {
        name
        for name, value in root_values.items()
        if isinstance(value, str)
        and _ENUM_LITERAL.fullmatch(value)
        and not value.startswith(ENGINE_ENUM_PACKAGES)
        # Templates.Plants application/actuator enums have their own grounder
        # (G36Library._ground_compile_time_enum_parameters), which also strips them
        and not value.startswith("Buildings.Templates.Plants.Controls.Types.")
    }
    if not special:
        return []
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in sorted(special)) + r")\b")
    component_prefixes = tuple(ref + "." for ref in _refs(root, "S231:containsBlock"))
    targets = [
        identifier
        for identifier in _refs(root, "S231:hasParameter")
        if by_id.get(identifier, {}).get("S231:isArray") is not True
    ] + [
        identifier
        for identifier, node in by_id.items()
        if identifier.startswith(component_prefixes) and "S231:value" in node
    ]
    grounded: list[dict[str, Any]] = []
    for _ in range(4):
        changed = False
        for identifier in targets:
            node = by_id.get(identifier, {})
            value = _literal(node.get("S231:value"))
            if not isinstance(value, str) or _ENUM_LITERAL.fullmatch(value.strip()):
                continue
            if not pattern.search(value) and "{" not in value:
                continue
            is_member = identifier.startswith(component_prefixes)
            try:
                result = _evaluate_parameter_text(
                    value, {**root_values, **arrays}, context=identifier
                )
            except CxfArrayScalarizationError:
                if not is_member:
                    continue
                try:
                    result = _parse_array_expression(
                        value, {**root_values, **arrays}, context=identifier
                    )
                except CxfArrayScalarizationError:
                    continue
            if isinstance(result, str) or (isinstance(result, list) and not is_member):
                continue
            node["S231:value"] = result
            if not is_member and not isinstance(result, list):
                root_values[identifier.rsplit(".", 1)[-1]] = result
            grounded.append({"parameter": identifier, "expression": value, "value": result})
            changed = True
        if not changed:
            break
    return grounded


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
    child_ports: ChildPortOracle | None = None,
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
        _VECTOR_FILTERS
        | set(_REDUCTIONS)
        | _SCALAR_REPLICATORS
        | set(_EXTRACTORS)
        | _EXTRACT_SIGNALS
        | set(_TIME_TABLES)
        | set(_MATRIX_REDUCTIONS)
        | set(_VECTOR_REPLICATORS)
        | {_MATRIX_GAIN, _LIMITER, _SORT}
    )
    admitted = set(INSTANCE_SCHEMAS) | elaborated_classes
    if classes and all(class_name in _VECTOR_REPLICATORS for class_name in classes):
        # A replicator-only composite keeps its dedicated expansion (explicit
        # identity blocks between its boundary connectors) below.
        return None
    root_values = _root_parameters(root, by_id)
    # A component whose class is a separately emitted composite is an opaque block
    # here: its ports come from its class (child_ports), its internals from its own
    # normalisation when the assembler instantiates it.
    opaque: dict[str, dict[str, ChildPort]] = {}
    for component, class_name in zip(components, classes, strict=True):
        assert component is not None
        if class_name in admitted:
            continue
        signature = child_ports(component, by_id, root_values) if child_ports else None
        if signature is None:
            return None
        opaque[str(component["@id"])] = signature

    def is_connector(node: dict[str, Any]) -> bool:
        raw = node.get("@type", [])
        values = raw if isinstance(raw, list) else [raw]
        return any(isinstance(v, str) and v.endswith(("Input", "Output")) for v in values)

    has_arrays = (
        any((component or {}).get("S231:isArray") is True for component in components)
        or any(node.get("S231:isArray") is True and is_connector(node) for node in graph)
        or any(shape for ports in opaque.values() for _, shape, _ in ports.values())
    )
    # The engine refuses array connectors and array instances inside a composite
    # document, so a composite holding any of them is scalarised whole, even when
    # it has no reduction or filter to elaborate.
    if not has_arrays and not any(class_name in elaborated_classes for class_name in classes):
        return None

    referenced: set[str] = set()
    for node in graph:
        targets = [
            item["@id"]
            for item in _items(node.get("S231:isConnectedTo"))
            if isinstance(item.get("@id"), str)
        ]
        if targets and isinstance(node.get("@id"), str):
            referenced.add(node["@id"])
        referenced.update(targets)
    referenced_bases: set[str] = set()
    for identifier in referenced:
        base = re.sub(r"\[[^\]]*\]$", "", unquote(identifier))
        referenced_bases.add(base)
        if "#" in base:
            referenced_bases.add("ex:" + base.split("#", 1)[1])
    # Array parameters leave the scalarised root (the engine refuses them on a
    # composite), so a child modification that names one takes its value instead.
    root_array_values = _grounded_array_parameters(root, by_id, root_values)
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
        if isinstance(value, str) and value.strip() in root_array_values:
            return root_array_values[value.strip()]
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
    extractor_count = 0
    sort_count = 0
    matrix_gain_count = 0
    limiter_count = 0
    expanded_component_count = 0
    inactive_endpoints: set[str] = set()
    # An array of elaborated constructs (``intRep1[nSta]`` of IntegerScalarReplicator,
    # nout=fill(nChi, nSta)) expands into one construct per element with its own
    # parameters; its endpoints are recombined under the array's name below.
    work: list[tuple[dict[str, Any], str]] = []
    construct_arrays: dict[str, tuple[tuple[int, ...], list[tuple[tuple[int, ...], str]]]] = {}
    for component, class_name in zip(components, classes, strict=True):
        assert component is not None
        component_id = str(component["@id"])
        if (
            class_name not in elaborated_classes
            or component_id in opaque
            or component.get("S231:isArray") is not True
        ):
            work.append((component, class_name))
            continue
        array_shape = _shape(component, root_values)
        elements: list[tuple[tuple[int, ...], str]] = []
        for element_index in _indices(array_shape):
            element_id = _scalar_id(component_id, element_index)
            element = copy.deepcopy(component)
            element["@id"] = element_id
            for field in _ARRAY_FIELDS:
                element.pop(field, None)
            for identifier, node in list(by_id.items()):
                if identifier.startswith(component_id + ".") and "S231:value" in node:
                    by_id[element_id + identifier[len(component_id) :]] = {
                        "@id": element_id + identifier[len(component_id) :],
                        "S231:value": _element_expression(
                            node["S231:value"],
                            element_index,
                            root_array_values,
                            context=identifier,
                        ),
                    }
            work.append((element, class_name))
            elements.append((element_index, element_id))
        construct_arrays[component_id] = (array_shape, elements)

    for component, class_name in work:
        assert component is not None
        component_id = str(component["@id"])
        if component_id in opaque:
            # An array of composite instances (``heaPreCon[nChi]``) becomes one instance
            # per element, each assembled on its own; its ports gain the instance index.
            instance_shape = (
                _shape(component, root_values) if component.get("S231:isArray") is True else ()
            )
            instance_indices = _indices(instance_shape) if instance_shape else [()]
            prefix = component_id + "."
            signature = opaque[component_id]
            base_label = re.sub(
                r"\s*\[[^]]*\]\s*$",
                "",
                str(component.get("S231:label", component_id.rsplit(".", 1)[-1])),
            )
            for instance_index in instance_indices:
                instance_id = (
                    _scalar_id(component_id, instance_index) if instance_index else component_id
                )
                kept = copy.deepcopy(component)
                kept.pop("S231:isConnectedTo", None)
                kept["@id"] = instance_id
                if instance_index:
                    for field in _ARRAY_FIELDS:
                        kept.pop(field, None)
                    kept["S231:label"] = (
                        base_label + "__" + "_".join(str(item) for item in instance_index)
                    )
                    _set_refs(
                        kept,
                        "S231:hasInstance",
                        [
                            instance_id + reference[len(component_id) :]
                            if reference.startswith(prefix)
                            else reference
                            for reference in _refs(component, "S231:hasInstance")
                        ],
                    )
                register(kept)
                new_component_ids.append(instance_id)
                for identifier, node in by_id.items():
                    if not identifier.startswith(prefix) or identifier in signature:
                        continue
                    member_id = instance_id + identifier[len(component_id) :]
                    if member_id in node_by_id:
                        continue
                    member = copy.deepcopy(node)
                    member.pop("S231:isConnectedTo", None)
                    member["@id"] = member_id
                    if "S231:value" in member:
                        if instance_index:
                            member["S231:value"] = _element_expression(
                                member["S231:value"],
                                instance_index,
                                root_array_values,
                                context=identifier,
                            )
                        else:
                            value = _literal(member["S231:value"])
                            if isinstance(value, str) and value in root_array_values:
                                member["S231:value"] = copy.deepcopy(root_array_values[value])
                            elif isinstance(value, str) and value.strip().startswith(
                                ("{", "fill(")
                            ):
                                # An array modification is an expression of this scope
                                # (``chiTypInt={if chiTyp[i] == ... for i in 1:nChi}``):
                                # the child cannot see ``chiTyp``, so ground it here.
                                try:
                                    member["S231:value"] = _parse_array_expression(
                                        value,
                                        {**root_values, **root_array_values},
                                        context=identifier,
                                    )
                                except CxfArrayScalarizationError:
                                    pass
                    register(member)
            for port_id, (direction, port_shape, port_type) in signature.items():
                if port_id not in referenced_bases:
                    continue
                local = port_id[len(component_id) :]
                endpoint_shapes[port_id] = instance_shape + port_shape
                endpoint_maps[port_id] = {}
                for instance_index in instance_indices:
                    instance_id = (
                        _scalar_id(component_id, instance_index) if instance_index else component_id
                    )
                    for index in _indices(port_shape) if port_shape else [()]:
                        base = instance_id + local
                        identifier = _scalar_id(base, index) if index else base
                        stub = (
                            {} if index or instance_index else copy.deepcopy(by_id.get(port_id, {}))
                        )
                        stub.pop("S231:isConnectedTo", None)
                        for field in _ARRAY_FIELDS:
                            stub.pop(field, None)
                        stub["@id"] = identifier
                        if port_type is not None:
                            stub["@type"] = port_type
                        register(stub, direction)
                        endpoint_maps[port_id][instance_index + index] = identifier
            continue
        if class_name in _VECTOR_REPLICATORS:
            nin = _component_parameter(component_id, "nin", by_id, root_values)
            nout = _component_parameter(component_id, "nout", by_id, root_values)
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(output_base, (nout, nin))
            for row in range(1, nout + 1):
                for column in range(1, nin + 1):
                    disjoint.union(
                        endpoint_maps[input_base][(column,)],
                        endpoint_maps[output_base][(row, column)],
                    )
            scalar_replicator_count += 1
            continue
        if class_name in _MATRIX_REDUCTIONS:
            rows = _component_parameter(component_id, "nRow", by_id, root_values)
            columns = _component_parameter(component_id, "nCol", by_id, root_values)
            row_wise = (
                component_value(component_id, "rowMax" if "Max" in class_name else "rowMin")
                if by_id.get(f"{component_id}.{'rowMax' if 'Max' in class_name else 'rowMin'}")
                else True
            )
            if not isinstance(row_wise, bool):
                raise CxfArrayScalarizationError(f"{component_id} axis must be Boolean")
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            count = rows if row_wise else columns
            dynamic_endpoint(input_base, (rows, columns))
            dynamic_endpoint(output_base, (count,))
            for element in range(1, count + 1):
                members = (
                    [(element, column) for column in range(1, columns + 1)]
                    if row_wise
                    else [(row, element) for row in range(1, rows + 1)]
                )
                accumulator = endpoint_maps[input_base][members[0]]
                for position, member in enumerate(members[1:], start=2):
                    fold_id = f"{component_id}__fold_{element}_{position}"
                    register(
                        _component(
                            fold_id,
                            _MATRIX_REDUCTIONS[class_name],
                            f"{component.get('S231:label', component_id)} {element} "
                            f"fold {position}",
                            [f"{fold_id}.u1", f"{fold_id}.u2", f"{fold_id}.y"],
                        )
                    )
                    register(_port(f"{fold_id}.u1"), "sink")
                    register(_port(f"{fold_id}.u2"), "sink")
                    register(_port(f"{fold_id}.y"), "source")
                    new_component_ids.append(fold_id)
                    disjoint.union(accumulator, f"{fold_id}.u1")
                    disjoint.union(endpoint_maps[input_base][member], f"{fold_id}.u2")
                    accumulator = f"{fold_id}.y"
                disjoint.union(accumulator, endpoint_maps[output_base][(element,)])
            reduction_count += 1
            continue
        if class_name == _SORT:
            # Modelica.Math.Vectors.sort (the engine mirrors it): shellsort whose
            # insertion step swaps only on a strict comparison. Without NaN inputs the
            # full compare-exchange sequence below produces the same values and the
            # same source indices, ties included (equal values never swap).
            nin = _component_parameter(component_id, "nin", by_id, root_values)
            ascending = (
                component_value(component_id, "ascending")
                if by_id.get(f"{component_id}.ascending")
                else True
            )
            if not isinstance(ascending, bool):
                raise CxfArrayScalarizationError(f"{component_id}.ascending must be Boolean")
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            index_base = f"{component_id}.yIdx"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(output_base, (nin,))
            dynamic_endpoint(index_base, (nin,))
            label = str(component.get("S231:label", component_id))
            values = [endpoint_maps[input_base][(element,)] for element in range(1, nin + 1)]
            indices: list[str] = []
            for element in range(1, nin + 1):
                constant_id = f"{component_id}__index_{element}"
                register(
                    _component(
                        constant_id,
                        "Buildings.Controls.OBC.CDL.Integers.Sources.Constant",
                        f"{label} index {element}",
                        [f"{constant_id}.k", f"{constant_id}.y"],
                    )
                )
                register({"@id": f"{constant_id}.k", "S231:isFinal": True, "S231:value": element})
                register(_port(f"{constant_id}.y"), "source")
                new_component_ids.append(constant_id)
                indices.append(f"{constant_id}.y")
            exchange = 0
            gap = nin // 2
            while gap > 0:
                for start in range(gap, nin):
                    position = start - gap
                    while position >= 0:
                        exchange += 1
                        compare_id = f"{component_id}__cmp_{exchange}"
                        left, right = position, position + gap
                        register(
                            _component(
                                compare_id,
                                "Buildings.Controls.OBC.CDL.Reals.Greater",
                                f"{label} compare {exchange}",
                                [f"{compare_id}.u1", f"{compare_id}.u2", f"{compare_id}.y"],
                            )
                        )
                        register(_port(f"{compare_id}.u1"), "sink")
                        register(_port(f"{compare_id}.u2"), "sink")
                        register(_port(f"{compare_id}.y"), "source")
                        new_component_ids.append(compare_id)
                        # ascending swaps when left > right, descending when right > left
                        first, second = (
                            (values[left], values[right])
                            if ascending
                            else (values[right], values[left])
                        )
                        disjoint.union(first, f"{compare_id}.u1")
                        disjoint.union(second, f"{compare_id}.u2")
                        swapped: dict[str, str] = {}
                        for lane, pair, switch_class in (
                            ("low", (values[right], values[left]), "Reals.Switch"),
                            ("high", (values[left], values[right]), "Reals.Switch"),
                            ("lowIdx", (indices[right], indices[left]), "Integers.Switch"),
                            ("highIdx", (indices[left], indices[right]), "Integers.Switch"),
                        ):
                            switch_id = f"{component_id}__{lane}_{exchange}"
                            register(
                                _component(
                                    switch_id,
                                    "Buildings.Controls.OBC.CDL." + switch_class,
                                    f"{label} {lane} {exchange}",
                                    [
                                        f"{switch_id}.u1",
                                        f"{switch_id}.u2",
                                        f"{switch_id}.u3",
                                        f"{switch_id}.y",
                                    ],
                                )
                            )
                            for slot in ("u1", "u2", "u3"):
                                register(_port(f"{switch_id}.{slot}"), "sink")
                            register(_port(f"{switch_id}.y"), "source")
                            new_component_ids.append(switch_id)
                            disjoint.union(pair[0], f"{switch_id}.u1")
                            disjoint.union(f"{compare_id}.y", f"{switch_id}.u2")
                            disjoint.union(pair[1], f"{switch_id}.u3")
                            swapped[lane] = f"{switch_id}.y"
                        values[left], values[right] = swapped["low"], swapped["high"]
                        indices[left], indices[right] = swapped["lowIdx"], swapped["highIdx"]
                        position -= gap
                gap //= 2
            for element in range(1, nin + 1):
                disjoint.union(values[element - 1], endpoint_maps[output_base][(element,)])
                disjoint.union(indices[element - 1], endpoint_maps[index_base][(element,)])
            sort_count += 1
            continue
        if class_name in _EXTRACTORS:
            nin = _component_parameter(component_id, "nin", by_id, root_values)
            input_base = f"{component_id}.u"
            index_base = f"{component_id}.index"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(index_base, ())
            dynamic_endpoint(output_base, ())
            selected = endpoint_maps[input_base][(nin,)]
            for element in range(nin - 1, 0, -1):
                test_id = f"{component_id}__atMost_{element}"
                switch_id = f"{component_id}__select_{element}"
                label = str(component.get("S231:label", component_id))
                register(
                    _component(
                        test_id,
                        "Buildings.Controls.OBC.CDL.Integers.LessThreshold",
                        f"{label} index <= {element}",
                        [f"{test_id}.t", f"{test_id}.u", f"{test_id}.y"],
                    )
                )
                register({"@id": f"{test_id}.t", "S231:isFinal": True, "S231:value": element + 1})
                register(_port(f"{test_id}.u"), "sink")
                register(_port(f"{test_id}.y"), "source")
                register(
                    _component(
                        switch_id,
                        _EXTRACTORS[class_name],
                        f"{label} element {element}",
                        [f"{switch_id}.u1", f"{switch_id}.u2", f"{switch_id}.u3", f"{switch_id}.y"],
                    )
                )
                for slot in ("u1", "u2", "u3"):
                    register(_port(f"{switch_id}.{slot}"), "sink")
                register(_port(f"{switch_id}.y"), "source")
                new_component_ids.extend([test_id, switch_id])
                disjoint.union(endpoint_maps[index_base][()], f"{test_id}.u")
                disjoint.union(f"{test_id}.y", f"{switch_id}.u2")
                disjoint.union(endpoint_maps[input_base][(element,)], f"{switch_id}.u1")
                disjoint.union(selected, f"{switch_id}.u3")
                selected = f"{switch_id}.y"
            disjoint.union(selected, endpoint_maps[output_base][()])
            extractor_count += 1
            continue
        if class_name in _TIME_TABLES:
            table = component_value(component_id, "table")
            rows = (
                table
                if isinstance(table, list)
                else _parse_array_expression(
                    str(table),
                    {**root_values, **root_array_values},
                    context=f"{component_id}.table",
                )
            )
            if (
                not rows
                or not all(isinstance(row, list) and len(row) >= 2 for row in rows)
                or len({len(row) for row in rows}) != 1
            ):
                raise CxfArrayScalarizationError(
                    f"{component_id}.table must be a rectangular matrix with a time column"
                )
            offsets: list[float] = []
            if class_name.endswith("Reals.Sources.TimeTable") and by_id.get(
                f"{component_id}.offset"
            ):
                offsets = [
                    float(value)
                    for value in _flatten(
                        _parse_array_expression(
                            component_value(component_id, "offset"),
                            {**root_values, **root_array_values},
                            context=f"{component_id}.offset",
                        )
                    )
                ]
            nout = len(rows[0]) - 1
            output_base = f"{component_id}.y"
            dynamic_endpoint(output_base, (nout,))
            label = str(component.get("S231:label", component_id))
            for column in range(1, nout + 1):
                values = [float(row[column]) for row in rows]
                if class_name.endswith("Reals.Sources.TimeTable"):
                    distinct = set(values)
                    constant: Any = values[0] + (offsets[column - 1] if offsets else 0.0)
                else:
                    levels = [math.floor(value + _TIME_TABLE_SMALL) for value in values]
                    distinct = set(levels)
                    constant = (
                        levels[0] > 0
                        if class_name.endswith("Logical.Sources.TimeTable")
                        else levels[0]
                    )
                if len(distinct) != 1:
                    raise CxfArrayScalarizationError(
                        f"{component_id} column {column} is a time-varying schedule; the "
                        "engine's CXF subset cannot hold a time table and BACTalk has no "
                        "schedule kind yet (only constant columns are rewritten)"
                    )
                constant_id = f"{component_id}__column_{column}"
                register(
                    _component(
                        constant_id,
                        _TIME_TABLES[class_name],
                        f"{label} column {column} (constant schedule)",
                        [f"{constant_id}.k", f"{constant_id}.y"],
                    )
                )
                register({"@id": f"{constant_id}.k", "S231:isFinal": True, "S231:value": constant})
                register(_port(f"{constant_id}.y"), "source")
                new_component_ids.append(constant_id)
                disjoint.union(f"{constant_id}.y", endpoint_maps[output_base][(column,)])
            scalar_replicator_count += 1
            continue
        if class_name in _EXTRACT_SIGNALS:
            nin = _component_parameter(component_id, "nin", by_id, root_values)
            nout = _component_parameter(component_id, "nout", by_id, root_values)
            extract_value = (
                component_value(component_id, "extract")
                if by_id.get(f"{component_id}.extract")
                else list(range(1, nout + 1))
            )
            extract = _flatten(
                extract_value
                if isinstance(extract_value, list)
                else _parse_array_expression(
                    str(extract_value),
                    {**root_values, **root_array_values},
                    context=f"{component_id}.extract",
                )
            )
            if len(extract) != nout or any(
                isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= nin
                for item in extract
            ):
                raise CxfArrayScalarizationError(
                    f"{component_id}.extract must hold {nout} indices from 1 to {nin}"
                )
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(output_base, (nout,))
            for output_index, source_index in enumerate(extract, start=1):
                disjoint.union(
                    endpoint_maps[input_base][(source_index,)],
                    endpoint_maps[output_base][(output_index,)],
                )
            scalar_replicator_count += 1
            continue
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
                {**root_values, **root_array_values},
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
                {**root_values, **root_array_values},
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
            gains: list[float] = []
            if class_name.endswith("MultiSum") and "S231:value" in by_id.get(
                f"{component_id}.k", {}
            ):
                gains = [
                    float(gain)
                    for gain in _flatten(
                        _parse_array_expression(
                            component_value(component_id, "k"),
                            {**root_values, **root_array_values},
                            context=f"{component_id}.k",
                        )
                    )
                ]
                if len(gains) != nin:
                    raise CxfArrayScalarizationError(f"{component_id}.k must have {nin} gains")
                if class_name.startswith("Buildings.Controls.OBC.CDL.Integers.") and any(
                    gain != 1.0 for gain in gains
                ):
                    raise CxfArrayScalarizationError(
                        f"{component_id}.k: Integer gains other than 1 are not expanded"
                    )
            input_base = f"{component_id}.u"
            output_base = f"{component_id}.y"
            dynamic_endpoint(input_base, (nin,))
            dynamic_endpoint(output_base, ())
            # y = sum(k[i] * u[i]): an input whose gain is not 1 passes through a
            # MultiplyByParameter before the fold (decision 016)
            terms = {index: endpoint_maps[input_base][(index,)] for index in range(1, nin + 1)}
            for index, gain in enumerate(gains, start=1):
                if gain == 1.0:
                    continue
                gain_id = f"{component_id}__gain_{index}"
                register(
                    _component(
                        gain_id,
                        "Buildings.Controls.OBC.CDL.Reals.MultiplyByParameter",
                        f"{component.get('S231:label', component_id)} gain {index}",
                        [f"{gain_id}.k", f"{gain_id}.u", f"{gain_id}.y"],
                    )
                )
                register({"@id": f"{gain_id}.k", "S231:isFinal": True, "S231:value": gain})
                register(_port(f"{gain_id}.u"), "sink")
                register(_port(f"{gain_id}.y"), "source")
                new_component_ids.append(gain_id)
                disjoint.union(terms[index], f"{gain_id}.u")
                terms[index] = f"{gain_id}.y"
            if nin == 1:
                disjoint.union(terms[1], endpoint_maps[output_base][()])
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
                        disjoint.union(terms[1], u1)
                    else:
                        disjoint.union(previous_output, u1)
                    disjoint.union(terms[input_index], u2)
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
                resolve_parameter_expression(component_value(component_id, "have_inp"), root_values)
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
            if not isinstance(have_input, bool) or not isinstance(have_placeholder, bool):
                raise CxfArrayScalarizationError(
                    f"{component_id} placeholder availability must resolve to Boolean"
                )
            active_input_slots = {"u"} if have_input else {"uPh"} if have_placeholder else set()
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
                            root_array_values.get(
                                raw_value.strip(), root_values.get(raw_value, raw_value)
                            )
                            if isinstance(raw_value, str)
                            else raw_value
                        )
                        if isinstance(resolved, list):
                            selected_value: Any = resolved
                            for dimension_index in index:
                                if not isinstance(selected_value, list) or dimension_index > len(
                                    selected_value
                                ):
                                    raise CxfArrayScalarizationError(
                                        f"{original_id} does not match component shape"
                                    )
                                selected_value = selected_value[dimension_index - 1]
                            resolved = selected_value
                            child["S231:value"] = selected_value
                        if isinstance(resolved, str) and (
                            resolved.strip().startswith("{") or resolved.strip().startswith("fill(")
                        ):
                            selected: Any = _parse_array_expression(
                                resolved,
                                {**root_values, **root_array_values},
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

    for component_id, (array_shape, elements) in construct_arrays.items():
        first = elements[0][1]
        slots = {key[len(first) :] for key in endpoint_maps if key.startswith(first + ".")}
        for slot in slots:
            combined: dict[tuple[int, ...], str] = {}
            for element_index, element_id in elements:
                for index, target in endpoint_maps[element_id + slot].items():
                    combined[element_index + index] = target
            endpoint_maps[component_id + slot] = combined
            endpoint_shapes[component_id + slot] = array_shape + endpoint_shapes[first + slot]

    external_edges: list[tuple[str, str]] = []
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
                if (
                    isinstance(target, str)
                    and target not in by_id
                    and not target.startswith(str(root["@id"]) + ".")
                ):
                    # An edge leaving this composite (a boundary port wired to its
                    # parent's connector) belongs to the parent's document; the
                    # composite assembler splices it. It is carried through unchanged;
                    # only a scalar port can carry it.
                    source_shape, source_map = source_selection
                    if source_shape:
                        raise CxfArrayScalarizationError(
                            f"array port {source} is wired outside its composite to {target}"
                        )
                    external_edges.append((source_map[()], target))
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
    for source_id, target in external_edges:
        node = node_by_id[source_id]
        _set_refs(node, "S231:isConnectedTo", [*_refs(node, "S231:isConnectedTo"), target])

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
        "extractor_count": extractor_count,
        "sort_count": sort_count,
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
    *,
    child_ports: ChildPortOracle | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Expand a reviewed subset of grounded CDL fixed-array semantics.

    The first admitted construct is the Boolean/Real VectorReplicator used by
    G36 ZoneStatusDuplicator. Each public array connector becomes an indexed
    scalar connector. Each replicated output gets an explicit scalar identity
    block, which keeps the result ordinary CXF and independently executable in
    OCE. Any mixed or unrecognized array structure remains untouched so the
    downstream validator continues to fail closed.
    """

    filter_reduction = _scalarize_filter_reduction_network(document, child_ports)
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
                if data_type in {"real", "integer"}:
                    parameter_id = f"{identity_id}.p"
                    input_port = f"{identity_id}.u"
                    output_port = f"{identity_id}.y"
                    generated.extend(
                        [
                            _component(
                                identity_id,
                                "Buildings.Controls.OBC.CDL.Reals.AddParameter"
                                if data_type == "real"
                                else "Buildings.Controls.OBC.CDL.Integers.AddParameter",
                                label,
                                [parameter_id, input_port, output_port],
                            ),
                            {
                                "@id": parameter_id,
                                "S231:isFinal": True,
                                "S231:value": 0.0 if data_type == "real" else 0,
                            },
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
