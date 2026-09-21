from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from bactalk.domain import Block, BlockKind, ControlGraph, DataType, Link


class CxfImportError(ValueError):
    """Raised when a CXF graph cannot be lowered without changing its meaning."""


ExecutionProfile = Literal["modelica_exact", "host_tick_v1"]


_BINARY: dict[str, BlockKind] = {
    "Buildings.Controls.OBC.CDL.Reals.Add": BlockKind.ADD,
    "Buildings.Controls.OBC.CDL.Reals.Subtract": BlockKind.SUBTRACT,
    "Buildings.Controls.OBC.CDL.Reals.Multiply": BlockKind.MULTIPLY,
    "Buildings.Controls.OBC.CDL.Reals.Divide": BlockKind.DIVIDE,
    "Buildings.Controls.OBC.CDL.Reals.Min": BlockKind.MINIMUM,
    "Buildings.Controls.OBC.CDL.Reals.Max": BlockKind.MAXIMUM,
    "Buildings.Controls.OBC.CDL.Reals.Greater": BlockKind.GREATER_THAN,
    "Buildings.Controls.OBC.CDL.Reals.Less": BlockKind.LESS_THAN,
    "Buildings.Controls.OBC.CDL.Logical.And": BlockKind.AND,
    "Buildings.Controls.OBC.CDL.Logical.Or": BlockKind.OR,
    "Buildings.Controls.OBC.CDL.Logical.Xor": BlockKind.XOR,
    "Buildings.Controls.OBC.CDL.Integers.Add": BlockKind.ADD,
    "Buildings.Controls.OBC.CDL.Integers.Subtract": BlockKind.SUBTRACT,
    "Buildings.Controls.OBC.CDL.Integers.Multiply": BlockKind.MULTIPLY,
    "Buildings.Controls.OBC.CDL.Integers.Divide": BlockKind.DIVIDE,
    "Buildings.Controls.OBC.CDL.Integers.Min": BlockKind.MINIMUM,
    "Buildings.Controls.OBC.CDL.Integers.Max": BlockKind.MAXIMUM,
}
_UNARY: dict[str, BlockKind] = {
    "Buildings.Controls.OBC.CDL.Logical.Not": BlockKind.NOT,
}
_THRESHOLD: dict[str, BlockKind] = {
    "Buildings.Controls.OBC.CDL.Reals.GreaterThreshold": BlockKind.GREATER_THAN,
    "Buildings.Controls.OBC.CDL.Reals.LessThreshold": BlockKind.LESS_THAN,
}
_PARAMETER_ARITHMETIC: dict[str, BlockKind] = {
    "Buildings.Controls.OBC.CDL.Reals.MultiplyByParameter": BlockKind.MULTIPLY,
    "Buildings.Controls.OBC.CDL.Reals.AddParameter": BlockKind.ADD,
}
_CONSTANTS: dict[str, BlockKind] = {
    "Buildings.Controls.OBC.CDL.Reals.Sources.Constant": BlockKind.NUMERIC_CONST,
    "Buildings.Controls.OBC.CDL.Logical.Sources.Constant": BlockKind.BOOLEAN_CONST,
    "Buildings.Controls.OBC.CDL.Integers.Sources.Constant": BlockKind.NUMERIC_CONST,
}
_SWITCHES: dict[str, BlockKind] = {
    "Buildings.Controls.OBC.CDL.Reals.Switch": BlockKind.NUMERIC_SWITCH,
    "Buildings.Controls.OBC.CDL.Logical.Switch": BlockKind.BOOLEAN_SWITCH,
    "Buildings.Controls.OBC.CDL.Integers.Switch": BlockKind.NUMERIC_SWITCH,
}
_NAMED_NUMERIC_CONSTANTS: dict[str, float] = {
    # modelica-json currently preserves these package constants as qualified
    # symbols instead of grounding them. Keep this reviewed table deliberately
    # narrow: unknown symbols fail closed in the numeric accessors below.
    "Buildings.Controls.OBC.ASHRAE.G36.Types.ZoneStates.heating": 1.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.ZoneStates.deadband": 2.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.ZoneStates.cooling": 3.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.FreezeProtectionStages.stage0": 0.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.FreezeProtectionStages.stage1": 1.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.FreezeProtectionStages.stage2": 2.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.FreezeProtectionStages.stage3": 3.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.occupied": 1.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.coolDown": 2.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.setUp": 3.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.warmUp": 4.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.setBack": 5.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.freezeProtection": 6.0,
    "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.unoccupied": 7.0,
}
TRIM_AND_RESPOND_CLASS = "Buildings.Controls.OBC.ASHRAE.G36.Generic.TrimAndRespond"
TRUE_FALSE_HOLD_CLASS = "Buildings.Controls.OBC.CDL.Logical.TrueFalseHold"
ASSERT_WARNING_CLASS = "Buildings.Controls.OBC.CDL.Utilities.Assert"
PID_WITH_ENABLE_CLASS = "Buildings.Controls.OBC.Utilities.PIDWithEnable"
PID_WITH_ENABLE_CLASS_SHORT = "Utilities.PIDWithEnable"
PID_WITH_ENABLE_CLASSES = frozenset({PID_WITH_ENABLE_CLASS, PID_WITH_ENABLE_CLASS_SHORT})
INITIALIZATION_CLASS = "Buildings.Templates.Plants.Controls.Utilities.Initialization"
INITIALIZATION_CLASS_SHORT = "Utilities.Initialization"
INITIALIZATION_CLASSES = frozenset({INITIALIZATION_CLASS, INITIALIZATION_CLASS_SHORT})
TIMER_WITH_RESET_CLASS = "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
TIMER_WITH_RESET_CLASS_SHORT = "Utilities.TimerWithReset"
TIMER_WITH_RESET_CLASSES = frozenset({TIMER_WITH_RESET_CLASS, TIMER_WITH_RESET_CLASS_SHORT})
PLACEHOLDER_BOOLEAN_CLASSES = frozenset(
    {
        "Buildings.Templates.Plants.Controls.Utilities.PlaceholderLogical",
        "Utilities.PlaceholderLogical",
    }
)
PLACEHOLDER_NUMERIC_CLASSES = frozenset(
    {
        "Buildings.Templates.Plants.Controls.Utilities.PlaceholderReal",
        "Utilities.PlaceholderReal",
        "Buildings.Templates.Plants.Controls.Utilities.PlaceholderInteger",
        "Utilities.PlaceholderInteger",
    }
)
PLACEHOLDER_CLASSES = PLACEHOLDER_BOOLEAN_CLASSES | PLACEHOLDER_NUMERIC_CLASSES
PLANT_INTEGER_REDUCTION_CLASSES = frozenset(
    {
        "Buildings.Templates.Plants.Controls.Utilities.MultiMaxInteger",
        "Utilities.MultiMaxInteger",
        "Buildings.Templates.Plants.Controls.Utilities.MultiMinInteger",
        "Utilities.MultiMinInteger",
    }
)
SUPPORTED_CLASSES = frozenset(
    {
        *_BINARY,
        *_UNARY,
        *_THRESHOLD,
        *_PARAMETER_ARITHMETIC,
        *_CONSTANTS,
        *_SWITCHES,
        "Buildings.Controls.OBC.CDL.Logical.TrueDelay",
        "Buildings.Controls.OBC.CDL.Reals.Abs",
        "Buildings.Controls.OBC.CDL.Reals.Hysteresis",
        "Buildings.Controls.OBC.CDL.Reals.PID",
        "Buildings.Controls.OBC.CDL.Conversions.BooleanToReal",
        "Buildings.Controls.OBC.CDL.Conversions.BooleanToInteger",
        "Buildings.Controls.OBC.CDL.Conversions.IntegerToReal",
        "Buildings.Controls.OBC.CDL.Integers.Equal",
        "Buildings.Controls.OBC.CDL.Integers.GreaterThreshold",
        "Buildings.Controls.OBC.CDL.Integers.GreaterEqualThreshold",
        "Buildings.Controls.OBC.CDL.Integers.LessThreshold",
        "Buildings.Controls.OBC.CDL.Integers.LessEqualThreshold",
        "Buildings.Controls.OBC.CDL.Logical.Edge",
        "Buildings.Controls.OBC.CDL.Logical.FallingEdge",
        "Buildings.Controls.OBC.CDL.Logical.Change",
        "Buildings.Controls.OBC.CDL.Logical.Latch",
        "Buildings.Controls.OBC.CDL.Logical.Nor",
        "Buildings.Controls.OBC.CDL.Logical.Pre",
        "Buildings.Controls.OBC.CDL.Logical.Timer",
        TRUE_FALSE_HOLD_CLASS,
        ASSERT_WARNING_CLASS,
        "Buildings.Controls.OBC.CDL.Reals.MovingAverage",
        "Buildings.Controls.OBC.CDL.Discrete.Sampler",
        "Buildings.Controls.OBC.CDL.Discrete.FirstOrderHold",
        "Buildings.Controls.OBC.CDL.Logical.Sources.SampleTrigger",
        "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler",
        "Buildings.Controls.OBC.CDL.Discrete.UnitDelay",
        "Buildings.Controls.OBC.CDL.Integers.Change",
        "Buildings.Controls.OBC.CDL.Reals.Line",
        "Buildings.Controls.OBC.CDL.Reals.PIDWithReset",
        *PID_WITH_ENABLE_CLASSES,
        TRIM_AND_RESPOND_CLASS,
        *INITIALIZATION_CLASSES,
        *TIMER_WITH_RESET_CLASSES,
        *PLACEHOLDER_CLASSES,
        *PLANT_INTEGER_REDUCTION_CLASSES,
    }
)
NIAGARA_UNSUPPORTED_CLASSES = frozenset(
    {
        "Buildings.Controls.OBC.CDL.Reals.MovingAverage",
        "Buildings.Controls.OBC.CDL.Discrete.Sampler",
        "Buildings.Controls.OBC.CDL.Discrete.FirstOrderHold",
        "Buildings.Controls.OBC.CDL.Logical.Sources.SampleTrigger",
        "Buildings.Controls.OBC.CDL.Discrete.UnitDelay",
        "Buildings.Controls.OBC.CDL.Integers.Change",
        "Buildings.Controls.OBC.CDL.Reals.Hysteresis",
        "Buildings.Controls.OBC.CDL.Reals.PID",
        "Buildings.Controls.OBC.CDL.Reals.PIDWithReset",
        *PID_WITH_ENABLE_CLASSES,
        "Buildings.Controls.OBC.CDL.Logical.FallingEdge",
        "Buildings.Controls.OBC.CDL.Logical.Latch",
        "Buildings.Controls.OBC.CDL.Logical.Pre",
        "Buildings.Controls.OBC.CDL.Logical.Timer",
        TRUE_FALSE_HOLD_CLASS,
        "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler",
        TRIM_AND_RESPOND_CLASS,
        *INITIALIZATION_CLASSES,
        *TIMER_WITH_RESET_CLASSES,
        ASSERT_WARNING_CLASS,
    }
)


def _schema(
    inputs: tuple[str, ...] = (),
    outputs: tuple[str, ...] = ("y",),
    parameters: tuple[str, ...] = (),
) -> dict[str, tuple[str, ...]]:
    return {"inputs": inputs, "outputs": outputs, "parameters": parameters}


# modelica-json uses S231:hasInput/hasOutput/hasParameter for older CXF files and
# S231:hasInstance for current composite translations. The latter intentionally
# omits type annotations on connector instances, so classification must come from
# a reviewed class contract rather than from heuristics.
INSTANCE_SCHEMAS: dict[str, dict[str, tuple[str, ...]]] = {
    **{name: _schema(("u1", "u2")) for name in _BINARY},
    **{name: _schema(("u",)) for name in _UNARY},
    **{name: _schema(("u",), parameters=("t",)) for name in _THRESHOLD},
    "Buildings.Controls.OBC.CDL.Reals.MultiplyByParameter": _schema(("u",), parameters=("k",)),
    "Buildings.Controls.OBC.CDL.Reals.AddParameter": _schema(("u",), parameters=("p",)),
    **{name: _schema(parameters=("k",)) for name in _CONSTANTS},
    **{name: _schema(("u1", "u2", "u3")) for name in _SWITCHES},
    "Buildings.Controls.OBC.CDL.Logical.TrueDelay": _schema(
        ("u",), parameters=("delayTime", "delayOnInit")
    ),
    "Buildings.Controls.OBC.CDL.Reals.Abs": _schema(("u",)),
    "Buildings.Controls.OBC.CDL.Reals.Hysteresis": _schema(
        ("u",), parameters=("uLow", "uHigh", "pre_y_start")
    ),
    "Buildings.Controls.OBC.CDL.Reals.PID": _schema(
        ("u_s", "u_m"),
        parameters=(
            "controllerType",
            "k",
            "Ti",
            "Td",
            "r",
            "yMax",
            "yMin",
            "Ni",
            "Nd",
            "xi_start",
            "yd_start",
            "reverseActing",
        ),
    ),
    "Buildings.Controls.OBC.CDL.Conversions.BooleanToReal": _schema(
        ("u",), parameters=("realTrue", "realFalse")
    ),
    "Buildings.Controls.OBC.CDL.Conversions.BooleanToInteger": _schema(
        ("u",), parameters=("integerTrue", "integerFalse")
    ),
    "Buildings.Controls.OBC.CDL.Conversions.IntegerToReal": _schema(("u",)),
    "Buildings.Controls.OBC.CDL.Integers.Equal": _schema(("u1", "u2")),
    "Buildings.Controls.OBC.CDL.Integers.GreaterThreshold": _schema(("u",), parameters=("t",)),
    "Buildings.Controls.OBC.CDL.Integers.GreaterEqualThreshold": _schema(("u",), parameters=("t",)),
    "Buildings.Controls.OBC.CDL.Integers.LessThreshold": _schema(("u",), parameters=("t",)),
    "Buildings.Controls.OBC.CDL.Integers.LessEqualThreshold": _schema(("u",), parameters=("t",)),
    "Buildings.Controls.OBC.CDL.Logical.Edge": _schema(("u",), parameters=("pre_u_start",)),
    "Buildings.Controls.OBC.CDL.Logical.FallingEdge": _schema(("u",), parameters=("pre_u_start",)),
    "Buildings.Controls.OBC.CDL.Logical.Change": _schema(("u",), parameters=("pre_u_start",)),
    "Buildings.Controls.OBC.CDL.Logical.Latch": _schema(("u", "clr")),
    "Buildings.Controls.OBC.CDL.Logical.Nor": _schema(("u1", "u2")),
    "Buildings.Controls.OBC.CDL.Logical.Pre": _schema(("u",), parameters=("pre_u_start",)),
    "Buildings.Controls.OBC.CDL.Logical.Timer": _schema(
        ("u",), outputs=("y", "passed"), parameters=("t",)
    ),
    TRUE_FALSE_HOLD_CLASS: _schema(("u",), parameters=("trueHoldDuration", "falseHoldDuration")),
    ASSERT_WARNING_CLASS: _schema(("u",), outputs=(), parameters=("message",)),
    "Buildings.Controls.OBC.CDL.Reals.MovingAverage": _schema(("u",), parameters=("delta",)),
    "Buildings.Controls.OBC.CDL.Discrete.Sampler": _schema(("u",), parameters=("samplePeriod",)),
    "Buildings.Controls.OBC.CDL.Discrete.FirstOrderHold": _schema(
        ("u",), parameters=("samplePeriod",)
    ),
    "Buildings.Controls.OBC.CDL.Logical.Sources.SampleTrigger": _schema(
        parameters=("period", "shift")
    ),
    "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler": _schema(
        ("u", "trigger"), parameters=("y_start",)
    ),
    "Buildings.Controls.OBC.CDL.Discrete.UnitDelay": _schema(
        ("u",), parameters=("samplePeriod", "y_start")
    ),
    "Buildings.Controls.OBC.CDL.Integers.Change": _schema(
        ("u",), ("y", "up", "down"), ("pre_u_start",)
    ),
    "Buildings.Controls.OBC.CDL.Reals.Line": _schema(
        ("x1", "f1", "x2", "f2", "u"),
        parameters=("limitBelow", "limitAbove"),
    ),
    "Buildings.Controls.OBC.CDL.Reals.PIDWithReset": _schema(
        ("u_s", "u_m", "trigger"),
        parameters=(
            "controllerType",
            "k",
            "Ti",
            "Td",
            "r",
            "yMax",
            "yMin",
            "Ni",
            "Nd",
            "xi_start",
            "yd_start",
            "reverseActing",
            "y_reset",
        ),
    ),
    **{
        class_name: _schema(
            ("u_s", "u_m", "uEna"),
            parameters=(
                "controllerType",
                "k",
                "Ti",
                "Td",
                "r",
                "yMax",
                "yMin",
                "Ni",
                "Nd",
                "reverseActing",
                "y_reset",
                "y_neutral",
            ),
        )
        for class_name in PID_WITH_ENABLE_CLASSES
    },
    TRIM_AND_RESPOND_CLASS: _schema(
        ("numOfReq", "uDevSta", "uHol"),
        parameters=(
            "have_hol",
            "iniSet",
            "minSet",
            "maxSet",
            "delTim",
            "samplePeriod",
            "numIgnReq",
            "triAmo",
            "resAmo",
            "maxRes",
            "dtHol",
        ),
    ),
    INITIALIZATION_CLASS: _schema(("u",), parameters=("yIni",)),
    INITIALIZATION_CLASS_SHORT: _schema(("u",), parameters=("yIni",)),
    TIMER_WITH_RESET_CLASS: _schema(("u", "reset"), outputs=("y", "passed"), parameters=("t",)),
    TIMER_WITH_RESET_CLASS_SHORT: _schema(
        ("u", "reset"), outputs=("y", "passed"), parameters=("t",)
    ),
    **{
        class_name: _schema(
            ("u", "uPh"),
            parameters=("have_inp", "have_inpPh", "u_internal"),
        )
        for class_name in PLACEHOLDER_CLASSES
    },
    **{
        class_name: _schema(("u",), parameters=("nin",))
        for class_name in PLANT_INTEGER_REDUCTION_CLASSES
    },
}


def _items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _refs(node: dict[str, Any], key: str) -> list[str]:
    return [item["@id"] for item in _items(node.get(key)) if "@id" in item]


def _suffix(value: str) -> str:
    suffix = value.rsplit("#", 1)[-1]
    # modelica-json emits compact JSON-LD identifiers such as
    # ``ex:Buildings.Controls...``. The lowering table intentionally stores
    # namespace-independent Modelica class names.
    suffix = suffix.removeprefix("ex:")
    # Some G36 sources reference CDL classes relative to the ``Buildings.Controls.OBC``
    # package (``CDL.Logical.Not``); qualify them so one table covers both spellings.
    if suffix.startswith("CDL."):
        suffix = "Buildings.Controls.OBC." + suffix
    return suffix


def _local_name(value: str) -> str:
    return re.split(r"[.#]", value)[-1]


def _identifier(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_") or fallback
    if not cleaned[0].isalpha() and cleaned[0] != "_":
        cleaned = f"n_{cleaned}"
    return cleaned


def _literal(value: Any) -> float | bool | str:
    if isinstance(value, dict) and "@value" in value:
        raw = value["@value"]
        datatype = str(value.get("@type", ""))
        if datatype.endswith("boolean"):
            return str(raw).lower() == "true"
        if datatype.endswith(("double", "decimal", "float", "integer", "int")):
            return float(raw)
        return raw
    if isinstance(value, (bool, int, float, str)):
        return value
    raise CxfImportError(f"unsupported CXF literal: {value!r}")


def _data_type(node: dict[str, Any]) -> DataType:
    types = node.get("@type", [])
    values = types if isinstance(types, list) else [types]
    if any("Boolean" in str(value) for value in values):
        return DataType.BOOLEAN
    if any(token in str(value) for value in values for token in ("Real", "Integer")):
        return DataType.NUMERIC
    declared = node.get("S231:isOfDataType", {}).get("@id", "")
    if "Boolean" in declared:
        return DataType.BOOLEAN
    if "Real" in declared or "Integer" in declared:
        return DataType.NUMERIC
    raise CxfImportError(f"CXF connector {node.get('@id')} has no supported data type")


def _numeric_parameter(
    parameters: dict[str, float | bool | str],
    label: str,
    name: str,
    default: float,
) -> float:
    value = parameters.get(name, default)
    if isinstance(value, str) and value in _NAMED_NUMERIC_CONSTANTS:
        value = _NAMED_NUMERIC_CONSTANTS[value]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CxfImportError(f"{label} requires numeric {name} parameter")
    return float(value)


def resolve_parameter_expression(
    value: float | bool | str,
    values: dict[str, float | bool | str],
) -> float | bool | str:
    if not isinstance(value, str):
        return value
    if value in values and values[value] != value:
        return values[value]
    conditional = re.fullmatch(
        r"\s*if\s+(.+?)\s+then\s+(.+?)\s+else\s+(.+?)\s*",
        value,
    )
    if conditional is not None:
        condition = resolve_parameter_expression(conditional.group(1), values)
        if isinstance(condition, bool):
            branch = conditional.group(2) if condition else conditional.group(3)
            return resolve_parameter_expression(branch, values)
    try:
        expression = ast.parse(value, mode="eval")
    except SyntaxError:
        return value

    def evaluate(node: ast.AST) -> float | bool | str:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id.lower() in {"true", "false"}:
                return node.id.lower() == "true"
            resolved = values.get(node.id)
            if not isinstance(resolved, (bool, int, float, str)):
                raise ValueError(node.id)
            return resolved
        if isinstance(node, ast.Attribute):
            parts: list[str] = []
            current: ast.AST = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if not isinstance(current, ast.Name):
                raise ValueError("attribute")
            parts.append(current.id)
            name = ".".join(reversed(parts))
            return values.get(name, name)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operand = evaluate(node.operand)
            if not isinstance(operand, bool):
                raise ValueError("not-non-boolean")
            return not operand
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = evaluate(node.operand)
            if isinstance(operand, bool) or not isinstance(operand, (int, float)):
                raise ValueError("numeric-unary")
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if (
                isinstance(left, bool)
                or isinstance(right, bool)
                or not isinstance(left, (int, float))
                or not isinstance(right, (int, float))
            ):
                raise ValueError("numeric-binary")
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            operands = [evaluate(value) for value in node.values]
            if not all(isinstance(operand, bool) for operand in operands):
                raise ValueError("boolean-operator")
            return all(operands) if isinstance(node.op, ast.And) else any(operands)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left = evaluate(node.left)
            right = evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise ValueError(type(node).__name__)

    try:
        return evaluate(expression)
    except (ValueError, ZeroDivisionError, OverflowError):
        return value


def _pid_config(
    parameters: dict[str, float | bool | str],
    label: str,
    *,
    with_reset: bool,
) -> dict[str, Any]:
    raw_controller = parameters.get("controllerType", "PI")
    if not isinstance(raw_controller, str):
        raise CxfImportError(f"{label} controllerType must be an enum member")
    controller_type = raw_controller.rsplit(".", 1)[-1]
    reverse_acting = parameters.get("reverseActing", True)
    if not isinstance(reverse_acting, bool):
        raise CxfImportError(f"{label} reverseActing must be Boolean")
    xi_start = _numeric_parameter(parameters, label, "xi_start", 0.0)
    config = {
        "controller_type": controller_type,
        "k": _numeric_parameter(parameters, label, "k", 1.0),
        "ti": _numeric_parameter(parameters, label, "Ti", 0.5),
        "td": _numeric_parameter(parameters, label, "Td", 0.1),
        "r": _numeric_parameter(parameters, label, "r", 1.0),
        "y_max": _numeric_parameter(parameters, label, "yMax", 1.0),
        "y_min": _numeric_parameter(parameters, label, "yMin", 0.0),
        "ni": _numeric_parameter(parameters, label, "Ni", 0.9),
        "nd": _numeric_parameter(parameters, label, "Nd", 10.0),
        "xi_start": xi_start,
        "yd_start": _numeric_parameter(parameters, label, "yd_start", 0.0),
        "y_reset": _numeric_parameter(parameters, label, "y_reset", xi_start),
        "reverse_acting": reverse_acting,
    }
    if not with_reset:
        config["y_reset"] = xi_start
    return config


class CxfImporter:
    """Lower a strict, documented subset of ASHRAE 231P CXF into BACTalk IR."""

    mapping_version = "bactalk-cxf-lowering/v4"

    def load(self, source: Path) -> dict[str, Any]:
        return json.loads(source.read_text(encoding="utf-8"))

    @staticmethod
    def _component_refs(
        component: dict[str, Any],
        class_name: str,
        role: str,
    ) -> list[str]:
        fields = {
            "inputs": "S231:hasInput",
            "outputs": "S231:hasOutput",
            "parameters": "S231:hasParameter",
        }
        explicit = _refs(component, fields[role])
        if explicit:
            return explicit
        schema = INSTANCE_SCHEMAS.get(class_name)
        if schema is None:
            return []
        admitted = set(schema[role])
        return [
            identifier
            for identifier in _refs(component, "S231:hasInstance")
            if _local_name(identifier) in admitted
        ]

    @staticmethod
    def _root_parameters(
        root: dict[str, Any], by_id: dict[str, dict[str, Any]]
    ) -> dict[str, float | bool | str]:
        values: dict[str, float | bool | str] = {}
        for parameter_id in _refs(root, "S231:hasParameter"):
            parameter = by_id.get(parameter_id)
            if parameter is None or "S231:value" not in parameter:
                raise CxfImportError(f"missing value for root CXF parameter {parameter_id}")
            values[_local_name(parameter_id)] = _literal(parameter["S231:value"])
        for _ in range(max(1, len(values))):
            changed = False
            for name, value in list(values.items()):
                resolved = resolve_parameter_expression(value, values)
                if resolved != value:
                    values[name] = resolved
                    changed = True
            if not changed:
                break
        return values

    @classmethod
    def _parameters(
        cls,
        component: dict[str, Any],
        by_id: dict[str, dict[str, Any]],
        root_parameters: dict[str, float | bool | str] | None = None,
    ) -> dict[str, float | bool | str]:
        raw_type = component.get("@type", "")
        class_name = _suffix(raw_type) if isinstance(raw_type, str) else ""
        parameters: dict[str, float | bool | str] = {}
        explicit = set(_refs(component, "S231:hasParameter"))
        for parameter_id in cls._component_refs(component, class_name, "parameters"):
            parameter = by_id.get(parameter_id)
            if parameter is None or "S231:value" not in parameter:
                if parameter_id in explicit:
                    raise CxfImportError(f"missing value for CXF parameter {parameter_id}")
                continue
            value = _literal(parameter["S231:value"])
            if isinstance(value, str) and root_parameters:
                value = resolve_parameter_expression(value, root_parameters)
            if isinstance(value, str) and value in _NAMED_NUMERIC_CONSTANTS:
                value = _NAMED_NUMERIC_CONSTANTS[value]
            parameters[_local_name(parameter_id)] = value
        return parameters

    def inspect(
        self,
        document: dict[str, Any],
        *,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> dict[str, Any]:
        if execution_profile not in {"modelica_exact", "host_tick_v1"}:
            raise CxfImportError(f"unsupported CXF execution profile: {execution_profile!r}")
        nodes = document.get("@graph")
        if not isinstance(nodes, list):
            raise CxfImportError("CXF document must contain an @graph array")
        roots = [node for node in nodes if _refs(node, "S231:containsBlock")]
        if len(roots) != 1:
            raise CxfImportError(
                f"CXF must have exactly one root with containsBlock; found {len(roots)}"
            )
        by_id = {node.get("@id"): node for node in nodes if isinstance(node.get("@id"), str)}
        root = roots[0]
        root_parameters = self._root_parameters(root, by_id)
        classes: list[str] = []
        missing: list[str] = []
        for component_id in _refs(root, "S231:containsBlock"):
            component = by_id.get(component_id)
            if component is None:
                missing.append(component_id)
                continue
            raw_type = component.get("@type", "")
            if not isinstance(raw_type, str):
                missing.append(f"{component_id}:invalid-type")
                continue
            classes.append(_suffix(raw_type))
        counts = Counter(classes)
        unsupported = sorted(name for name in counts if name not in SUPPORTED_CLASSES)
        niagara_unsupported = sorted(name for name in counts if name in NIAGARA_UNSUPPORTED_CLASSES)
        serialized = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        exactness_blockers: list[str] = []
        niagara_exactness_blockers: list[str] = []
        if (
            "Buildings.Controls.OBC.CDL.Logical.Pre" in counts
            and execution_profile == "modelica_exact"
        ):
            exactness_blockers.append(
                "CDL.Logical.Pre requires same-time Modelica event iteration; select the "
                "explicit host_tick_v1 profile only when a one-call memory projection is "
                "acceptable"
            )
        for component_id in _refs(root, "S231:containsBlock"):
            component = by_id.get(component_id, {})
            if _suffix(str(component.get("@type", ""))) != (
                "Buildings.Controls.OBC.CDL.Logical.TrueDelay"
            ):
                continue
            parameters = self._parameters(component, by_id, root_parameters)
            if parameters.get("delayOnInit", False) is not True:
                niagara_exactness_blockers.append(
                    f"{component.get('S231:label', component_id)}: delayOnInit=false is not "
                    "equivalent to the Niagara BooleanDelay initialization used by this lowering"
                )
        return {
            "schema": self.mapping_version,
            "execution_profile": execution_profile,
            "source_sha256": hashlib.sha256(serialized).hexdigest(),
            "root_id": root["@id"],
            "root_label": root.get("S231:label", _local_name(root["@id"])),
            "component_count": len(classes),
            "boundary_inputs": len(_refs(root, "S231:hasInput")),
            "boundary_outputs": len(_refs(root, "S231:hasOutput")),
            "class_counts": dict(sorted(counts.items())),
            "supported_class_count": sum(
                count for name, count in counts.items() if name in SUPPORTED_CLASSES
            ),
            "unsupported_classes": unsupported,
            "niagara_unsupported_classes": niagara_unsupported,
            "missing_components": missing,
            "exactness_blockers": exactness_blockers,
            "niagara_exactness_blockers": niagara_exactness_blockers,
            "translatable": not unsupported and not missing and not exactness_blockers,
            "niagara_translatable": (
                not unsupported
                and not niagara_unsupported
                and not missing
                and not exactness_blockers
                and not niagara_exactness_blockers
            ),
        }

    def import_graph(
        self,
        document: dict[str, Any],
        *,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> ControlGraph:
        coverage = self.inspect(document, execution_profile=execution_profile)
        if not coverage["translatable"]:
            reasons = (
                coverage["unsupported_classes"]
                + coverage["missing_components"]
                + coverage["exactness_blockers"]
            )
            raise CxfImportError("CXF cannot be lowered exactly: " + "; ".join(reasons))

        nodes: list[dict[str, Any]] = document["@graph"]
        by_id = {node["@id"]: node for node in nodes if "@id" in node}
        root = by_id[coverage["root_id"]]
        root_parameters = self._root_parameters(root, by_id)
        blocks: list[Block] = []
        links: list[Link] = []
        input_ports: dict[str, list[tuple[str, str]]] = {}
        output_ports: dict[str, tuple[str, str]] = {}
        used_ids: set[str] = set()
        # Composite instance path of the CDL component each block came from,
        # relative to the controller root ("actAirSet.max2"); the native .bog
        # emitter folders the wiresheet by it (GOAL-NATIVE-BOG.md N4).
        origins: dict[str, str] = {}
        current_origin: str | None = None

        def unique_id(raw: str, fallback: str) -> str:
            base = _identifier(raw, fallback)
            candidate = base
            suffix = 2
            while candidate in used_ids:
                candidate = f"{base}_{suffix}"
                suffix += 1
            used_ids.add(candidate)
            if current_origin is not None:
                origins[candidate] = current_origin
            return candidate

        root_prefix = f"{coverage['root_id']}."

        for connector_id in _refs(root, "S231:hasInput"):
            connector = by_id[connector_id]
            block_id = unique_id(_local_name(connector_id), "Input")
            kind = (
                BlockKind.BOOLEAN_INPUT
                if _data_type(connector) == DataType.BOOLEAN
                else BlockKind.NUMERIC_INPUT
            )
            default: float | bool = False if kind == BlockKind.BOOLEAN_INPUT else 0.0
            blocks.append(
                Block(id=block_id, kind=kind, label=block_id, config={"default": default})
            )
            output_ports[connector_id] = (block_id, "out")

        for connector_id in _refs(root, "S231:hasOutput"):
            connector = by_id[connector_id]
            block_id = unique_id(_local_name(connector_id), "Output")
            kind = (
                BlockKind.BOOLEAN_OUTPUT
                if _data_type(connector) == DataType.BOOLEAN
                else BlockKind.NUMERIC_OUTPUT
            )
            blocks.append(Block(id=block_id, kind=kind, label=block_id))
            input_ports[connector_id] = [(block_id, "in")]

        for index, component_id in enumerate(_refs(root, "S231:containsBlock")):
            component = by_id[component_id]
            current_origin = (
                component_id[len(root_prefix) :]
                if component_id.startswith(root_prefix)
                else _local_name(component_id)
            )
            class_name = _suffix(component["@type"])
            label = str(component.get("S231:label", _local_name(component_id)))
            block_id = unique_id(label, f"Block_{index + 1}")
            parameters = self._parameters(component, by_id, root_parameters)
            component_inputs = self._component_refs(component, class_name, "inputs")
            output_ids = self._component_refs(component, class_name, "outputs")
            input_names = [_local_name(value) for value in component_inputs]
            config: dict[str, Any] = {}
            append_primary = True
            output_block_id = block_id
            expanded_inputs: dict[str, list[tuple[str, str]]] = {}
            expanded_outputs: dict[str, tuple[str, str]] = {}

            if class_name in _BINARY:
                kind = _BINARY[class_name]
                slot_map = {"u1": "a", "u2": "b"}
            elif class_name in _UNARY:
                kind = _UNARY[class_name]
                slot_map = {"u": "in"}
            elif class_name in _THRESHOLD:
                kind = _THRESHOLD[class_name]
                slot_map = {"u": "a"}
                threshold = parameters.get("t", 0.0)
                if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                    raise CxfImportError(f"{label} requires numeric threshold parameter t")
                constant_id = unique_id(f"{block_id}_threshold", "Threshold")
                blocks.append(
                    Block(
                        id=constant_id,
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"{label} threshold",
                        config={"value": float(threshold)},
                    )
                )
                links.append(Link(source=constant_id, target=block_id, target_slot="b"))
            elif class_name in {
                "Buildings.Controls.OBC.CDL.Integers.GreaterThreshold",
                "Buildings.Controls.OBC.CDL.Integers.GreaterEqualThreshold",
                "Buildings.Controls.OBC.CDL.Integers.LessThreshold",
                "Buildings.Controls.OBC.CDL.Integers.LessEqualThreshold",
            }:
                kind = {
                    "Buildings.Controls.OBC.CDL.Integers.GreaterThreshold": (
                        BlockKind.GREATER_THAN
                    ),
                    "Buildings.Controls.OBC.CDL.Integers.GreaterEqualThreshold": (
                        BlockKind.GREATER_THAN_OR_EQUAL
                    ),
                    "Buildings.Controls.OBC.CDL.Integers.LessThreshold": BlockKind.LESS_THAN,
                    "Buildings.Controls.OBC.CDL.Integers.LessEqualThreshold": (
                        BlockKind.LESS_THAN_OR_EQUAL
                    ),
                }[class_name]
                slot_map = {"u": "a"}
                threshold = parameters.get("t", 0.0)
                if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                    raise CxfImportError(f"{label} requires numeric threshold parameter t")
                constant_id = unique_id(f"{block_id}_threshold", "Threshold")
                blocks.append(
                    Block(
                        id=constant_id,
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"{label} threshold",
                        config={"value": float(threshold)},
                    )
                )
                links.append(Link(source=constant_id, target=block_id, target_slot="b"))
            elif class_name in _PARAMETER_ARITHMETIC:
                kind = _PARAMETER_ARITHMETIC[class_name]
                slot_map = {"u": "a"}
                value = parameters.get("k", parameters.get("p"))
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise CxfImportError(f"{label} requires a numeric k or p parameter")
                constant_id = unique_id(f"{block_id}_parameter", "Parameter")
                blocks.append(
                    Block(
                        id=constant_id,
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"{label} parameter",
                        config={"value": float(value)},
                    )
                )
                links.append(Link(source=constant_id, target=block_id, target_slot="b"))
            elif class_name in _CONSTANTS:
                kind = _CONSTANTS[class_name]
                slot_map = {}
                value = parameters.get("k")
                if kind == BlockKind.NUMERIC_CONST:
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise CxfImportError(f"{label} requires numeric constant parameter k")
                    config = {"value": float(value)}
                else:
                    if not isinstance(value, bool):
                        raise CxfImportError(f"{label} requires Boolean constant parameter k")
                    config = {"value": value}
            elif class_name in _SWITCHES:
                kind = _SWITCHES[class_name]
                slot_map = {"u1": "when_true", "u2": "selector", "u3": "when_false"}
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.TrueDelay":
                kind = BlockKind.BOOLEAN_DELAY
                slot_map = {"u": "in"}
                delay = parameters.get("delayTime")
                if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
                    raise CxfImportError(f"{label} requires non-negative delayTime")
                config = {
                    "on_delay_seconds": float(delay),
                    "off_delay_seconds": 0.0,
                    "initial": False,
                    "delay_on_init": bool(parameters.get("delayOnInit", False)),
                    "semantic_contract": "CDL.Logical.TrueDelay",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Reals.Abs":
                # abs(u) = if u >= 0 then u else 0 - u. This avoids relying on
                # kitControl:AbsValue, which pybog does not yet model.
                append_primary = False
                zero_id = unique_id(f"{block_id}_zero", "Zero")
                nonnegative_id = unique_id(f"{block_id}_nonnegative", "Nonnegative")
                negate_id = unique_id(f"{block_id}_negate", "Negate")
                output_block_id = unique_id(f"{block_id}_select", "Absolute")
                blocks.extend(
                    [
                        Block(
                            id=zero_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"{label} zero",
                            config={"value": 0.0},
                        ),
                        Block(
                            id=nonnegative_id,
                            kind=BlockKind.GREATER_THAN_OR_EQUAL,
                            label=f"{label} nonnegative",
                        ),
                        Block(
                            id=negate_id,
                            kind=BlockKind.SUBTRACT,
                            label=f"{label} negate",
                        ),
                        Block(
                            id=output_block_id,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=label,
                        ),
                    ]
                )
                links.extend(
                    [
                        Link(source=zero_id, target=nonnegative_id, target_slot="b"),
                        Link(source=zero_id, target=negate_id, target_slot="a"),
                        Link(
                            source=nonnegative_id,
                            target=output_block_id,
                            target_slot="selector",
                        ),
                        Link(
                            source=negate_id,
                            target=output_block_id,
                            target_slot="when_false",
                        ),
                    ]
                )
                expanded_inputs = {
                    "u": [
                        (nonnegative_id, "a"),
                        (negate_id, "b"),
                        (output_block_id, "when_true"),
                    ]
                }
                slot_map = {}
                kind = BlockKind.NUMERIC_SWITCH
            elif class_name == "Buildings.Controls.OBC.CDL.Reals.Hysteresis":
                kind = BlockKind.HYSTERESIS
                slot_map = {"u": "in"}
                low = _numeric_parameter(parameters, label, "uLow", 0.0)
                high = _numeric_parameter(parameters, label, "uHigh", 1.0)
                initial = parameters.get("pre_y_start", False)
                if not isinstance(initial, bool):
                    raise CxfImportError(f"{label} pre_y_start must be Boolean")
                config = {"u_low": low, "u_high": high, "initial": initial}
            elif class_name == "Buildings.Controls.OBC.CDL.Conversions.BooleanToReal":
                append_primary = False
                true_id = unique_id(f"{block_id}_true", "TrueValue")
                false_id = unique_id(f"{block_id}_false", "FalseValue")
                real_true = _numeric_parameter(parameters, label, "realTrue", 1.0)
                real_false = _numeric_parameter(parameters, label, "realFalse", 0.0)
                blocks.extend(
                    [
                        Block(
                            id=true_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"{label} true",
                            config={"value": real_true},
                        ),
                        Block(
                            id=false_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"{label} false",
                            config={"value": real_false},
                        ),
                        Block(id=block_id, kind=BlockKind.NUMERIC_SWITCH, label=label),
                    ]
                )
                links.extend(
                    [
                        Link(source=true_id, target=block_id, target_slot="when_true"),
                        Link(source=false_id, target=block_id, target_slot="when_false"),
                    ]
                )
                expanded_inputs = {"u": [(block_id, "selector")]}
                slot_map = {}
                kind = BlockKind.NUMERIC_SWITCH
            elif class_name == "Buildings.Controls.OBC.CDL.Conversions.BooleanToInteger":
                append_primary = False
                true_id = unique_id(f"{block_id}_true", "TrueValue")
                false_id = unique_id(f"{block_id}_false", "FalseValue")
                integer_true = _numeric_parameter(parameters, label, "integerTrue", 1.0)
                integer_false = _numeric_parameter(parameters, label, "integerFalse", 0.0)
                blocks.extend(
                    [
                        Block(
                            id=true_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"{label} true",
                            config={"value": integer_true},
                        ),
                        Block(
                            id=false_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"{label} false",
                            config={"value": integer_false},
                        ),
                        Block(id=block_id, kind=BlockKind.NUMERIC_SWITCH, label=label),
                    ]
                )
                links.extend(
                    [
                        Link(source=true_id, target=block_id, target_slot="when_true"),
                        Link(source=false_id, target=block_id, target_slot="when_false"),
                    ]
                )
                expanded_inputs = {"u": [(block_id, "selector")]}
                slot_map = {}
                kind = BlockKind.NUMERIC_SWITCH
            elif class_name == "Buildings.Controls.OBC.CDL.Conversions.IntegerToReal":
                # BACTalk represents CDL Integer and Real connectors as numeric.
                # Adding zero preserves a visible conversion boundary.
                zero_id = unique_id(f"{block_id}_zero", "Zero")
                kind = BlockKind.ADD
                slot_map = {"u": "a"}
                blocks.append(
                    Block(
                        id=zero_id,
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"{label} zero",
                        config={"value": 0.0},
                    )
                )
                links.append(Link(source=zero_id, target=block_id, target_slot="b"))
            elif class_name == "Buildings.Controls.OBC.CDL.Integers.Equal":
                kind = BlockKind.EQUAL
                slot_map = {"u1": "a", "u2": "b"}
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.Edge":
                kind = BlockKind.ONE_SHOT
                slot_map = {"u": "in"}
                config = {"initial": bool(parameters.get("pre_u_start", False))}
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.FallingEdge":
                kind = BlockKind.BOOLEAN_FALLING_EDGE
                slot_map = {"u": "in"}
                config = {
                    "pre_u_start": bool(parameters.get("pre_u_start", False)),
                    "semantic_contract": "CDL.Logical.FallingEdge",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.Change":
                append_primary = False
                rising_id = unique_id(f"{block_id}_rising", "Rising")
                invert_id = unique_id(f"{block_id}_invert", "Invert")
                falling_id = unique_id(f"{block_id}_falling", "Falling")
                output_block_id = unique_id(f"{block_id}_either", "Changed")
                initial = bool(parameters.get("pre_u_start", False))
                blocks.extend(
                    [
                        Block(
                            id=rising_id,
                            kind=BlockKind.ONE_SHOT,
                            label=f"{label} rising",
                            config={"initial": initial},
                        ),
                        Block(id=invert_id, kind=BlockKind.NOT, label=f"{label} invert"),
                        Block(
                            id=falling_id,
                            kind=BlockKind.ONE_SHOT,
                            label=f"{label} falling",
                            config={"initial": not initial},
                        ),
                        Block(id=output_block_id, kind=BlockKind.OR, label=label),
                    ]
                )
                links.extend(
                    [
                        Link(source=invert_id, target=falling_id, target_slot="in"),
                        Link(source=rising_id, target=output_block_id, target_slot="a"),
                        Link(source=falling_id, target=output_block_id, target_slot="b"),
                    ]
                )
                expanded_inputs = {"u": [(rising_id, "in"), (invert_id, "in")]}
                slot_map = {}
                kind = BlockKind.OR
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.Latch":
                kind = BlockKind.BOOLEAN_SET_RESET
                slot_map = {"u": "set", "clr": "clear"}
                config = {"semantic_contract": "CDL.Logical.Latch"}
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.Nor":
                append_primary = False
                or_id = unique_id(f"{block_id}_or", "Or")
                output_block_id = unique_id(f"{block_id}_not", "Nor")
                blocks.extend(
                    [
                        Block(id=or_id, kind=BlockKind.OR, label=f"{label} or"),
                        Block(id=output_block_id, kind=BlockKind.NOT, label=label),
                    ]
                )
                links.append(Link(source=or_id, target=output_block_id, target_slot="in"))
                expanded_inputs = {"u1": [(or_id, "a")], "u2": [(or_id, "b")]}
                slot_map = {}
                kind = BlockKind.NOT
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.Pre":
                kind = BlockKind.BOOLEAN_PRE_HOST_TICK
                slot_map = {"u": "in"}
                config = {
                    "initial": bool(parameters.get("pre_u_start", False)),
                    "semantic_contract": "CDL.Logical.Pre",
                    "execution_profile": "host_tick_v1",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.Timer":
                kind = BlockKind.TIMER
                slot_map = {"u": "in"}
                config = {
                    "threshold_seconds": _numeric_parameter(
                        parameters,
                        label,
                        "t",
                        0.0,
                    ),
                    "semantic_contract": "CDL.Logical.Timer",
                }
                expanded_outputs = {
                    "y": (block_id, "elapsed"),
                    "passed": (block_id, "passed"),
                }
            elif class_name in TIMER_WITH_RESET_CLASSES:
                kind = BlockKind.TIMER_WITH_RESET
                slot_map = {"u": "in", "reset": "reset"}
                config = {
                    "threshold_seconds": _numeric_parameter(
                        parameters,
                        label,
                        "t",
                        0.0,
                    ),
                    "semantic_contract": TIMER_WITH_RESET_CLASS,
                }
                expanded_outputs = {
                    "y": (block_id, "elapsed"),
                    "passed": (block_id, "passed"),
                }
            elif class_name in PLACEHOLDER_CLASSES:
                have_input = parameters.get("have_inp", True)
                have_placeholder_input = parameters.get("have_inpPh", False)
                if not isinstance(have_input, bool) or not isinstance(have_placeholder_input, bool):
                    raise CxfImportError(
                        f"{label} placeholder availability parameters must be Boolean"
                    )
                is_boolean = class_name in PLACEHOLDER_BOOLEAN_CLASSES
                append_primary = False
                if not have_input and not have_placeholder_input:
                    value = parameters.get("u_internal", False if is_boolean else 0.0)
                    if is_boolean:
                        if not isinstance(value, bool):
                            raise CxfImportError(
                                f"{label} logical placeholder value must be Boolean"
                            )
                        kind = BlockKind.BOOLEAN_CONST
                    else:
                        if isinstance(value, bool) or not isinstance(value, (int, float)):
                            raise CxfImportError(
                                f"{label} numeric placeholder value must be numeric"
                            )
                        kind = BlockKind.NUMERIC_CONST
                    blocks.append(
                        Block(
                            id=block_id,
                            kind=kind,
                            label=label,
                            config={"value": value},
                        )
                    )
                    output_block_id = block_id
                    expanded_inputs = {"u": [], "uPh": []}
                else:
                    constant_id = unique_id(f"{block_id}_identity", "IdentityConstant")
                    kind = BlockKind.OR if is_boolean else BlockKind.ADD
                    constant_kind = (
                        BlockKind.BOOLEAN_CONST if is_boolean else BlockKind.NUMERIC_CONST
                    )
                    blocks.extend(
                        [
                            Block(id=block_id, kind=kind, label=label),
                            Block(
                                id=constant_id,
                                kind=constant_kind,
                                label=f"{label} identity",
                                config={"value": False if is_boolean else 0.0},
                            ),
                        ]
                    )
                    links.append(Link(source=constant_id, target=block_id, target_slot="b"))
                    active_input = "u" if have_input else "uPh"
                    expanded_inputs = {active_input: [(block_id, "a")]}
                    output_block_id = block_id
                expanded_outputs = {"y": (output_block_id, "out")}
                slot_map = {}
            elif class_name == ASSERT_WARNING_CLASS:
                kind = BlockKind.BOOLEAN_ASSERT_WARNING
                slot_map = {"u": "condition"}
                message = parameters.get("message")
                if not isinstance(message, str):
                    raise CxfImportError(f"{label} requires String message parameter")
                try:
                    decoded_message = json.loads(message)
                except json.JSONDecodeError as exc:
                    raise CxfImportError(
                        f"{label} message is not a grounded CDL string literal"
                    ) from exc
                if not isinstance(decoded_message, str):
                    raise CxfImportError(f"{label} message must ground to String")
                config = {
                    "message": decoded_message,
                    "severity": "warning",
                    "repeat_while_false": True,
                    "semantic_contract": "CDL.Utilities.Assert",
                }
            elif class_name == TRUE_FALSE_HOLD_CLASS:
                kind = BlockKind.BOOLEAN_TRUE_FALSE_HOLD
                slot_map = {"u": "in"}
                true_hold = _numeric_parameter(
                    parameters,
                    label,
                    "trueHoldDuration",
                    0.0,
                )
                config = {
                    "true_hold_seconds": true_hold,
                    "false_hold_seconds": _numeric_parameter(
                        parameters,
                        label,
                        "falseHoldDuration",
                        true_hold,
                    ),
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Reals.MovingAverage":
                kind = BlockKind.MOVING_AVERAGE
                slot_map = {"u": "in"}
                window = parameters.get("delta")
                if isinstance(window, bool) or not isinstance(window, (int, float)):
                    raise CxfImportError(f"{label} requires numeric delta parameter")
                config = {
                    "window_seconds": float(window),
                    "semantic_contract": "CDL.Reals.MovingAverage",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Discrete.Sampler":
                kind = BlockKind.NUMERIC_SAMPLER
                slot_map = {"u": "in"}
                period = parameters.get("samplePeriod")
                if isinstance(period, bool) or not isinstance(period, (int, float)):
                    raise CxfImportError(f"{label} requires numeric samplePeriod parameter")
                config = {
                    "sample_period_seconds": float(period),
                    "semantic_contract": "CDL.Discrete.Sampler",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Discrete.FirstOrderHold":
                kind = BlockKind.NUMERIC_FIRST_ORDER_HOLD
                slot_map = {"u": "in"}
                period = parameters.get("samplePeriod")
                if isinstance(period, bool) or not isinstance(period, (int, float)):
                    raise CxfImportError(f"{label} requires numeric samplePeriod parameter")
                config = {
                    "sample_period_seconds": float(period),
                    "semantic_contract": "CDL.Discrete.FirstOrderHold",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Logical.Sources.SampleTrigger":
                kind = BlockKind.BOOLEAN_SAMPLE_TRIGGER
                slot_map = {}
                period = parameters.get("period")
                shift = parameters.get("shift", 0.0)
                if isinstance(period, bool) or not isinstance(period, (int, float)):
                    raise CxfImportError(f"{label} requires numeric period parameter")
                if isinstance(shift, bool) or not isinstance(shift, (int, float)):
                    raise CxfImportError(f"{label} requires numeric shift parameter")
                config = {
                    "period_seconds": float(period),
                    "shift_seconds": float(shift),
                    "semantic_contract": "CDL.Logical.Sources.SampleTrigger",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler":
                kind = BlockKind.NUMERIC_LATCH
                slot_map = {"u": "in", "trigger": "clock"}
                config = {
                    "initial": _numeric_parameter(parameters, label, "y_start", 0.0),
                    "semantic_contract": "CDL.Discrete.TriggeredSampler",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Discrete.UnitDelay":
                kind = BlockKind.NUMERIC_UNIT_DELAY
                slot_map = {"u": "in"}
                period = parameters.get("samplePeriod")
                initial = parameters.get("y_start", 0.0)
                if isinstance(period, bool) or not isinstance(period, (int, float)):
                    raise CxfImportError(f"{label} requires numeric samplePeriod parameter")
                if isinstance(initial, bool) or not isinstance(initial, (int, float)):
                    raise CxfImportError(f"{label} requires numeric y_start parameter")
                config = {
                    "sample_period_seconds": float(period),
                    "initial": float(initial),
                    "semantic_contract": "CDL.Discrete.UnitDelay",
                }
            elif class_name == "Buildings.Controls.OBC.CDL.Integers.Change":
                append_primary = False
                changed_id = unique_id(f"{block_id}_changed", "Changed")
                increased_id = unique_id(f"{block_id}_increased", "Increased")
                decreased_id = unique_id(f"{block_id}_decreased", "Decreased")
                initial = parameters.get("pre_u_start", 0.0)
                if isinstance(initial, bool) or not isinstance(initial, (int, float)):
                    raise CxfImportError(f"{label} requires numeric pre_u_start parameter")
                blocks.extend(
                    [
                        Block(
                            id=changed_id,
                            kind=BlockKind.NUMERIC_CHANGED,
                            label=f"{label} changed",
                            config={"initial": float(initial)},
                        ),
                        Block(
                            id=increased_id,
                            kind=BlockKind.NUMERIC_INCREASED,
                            label=f"{label} increased",
                            config={"initial": float(initial)},
                        ),
                        Block(
                            id=decreased_id,
                            kind=BlockKind.NUMERIC_DECREASED,
                            label=f"{label} decreased",
                            config={"initial": float(initial)},
                        ),
                    ]
                )
                expanded_inputs = {
                    "u": [
                        (changed_id, "in"),
                        (increased_id, "in"),
                        (decreased_id, "in"),
                    ]
                }
                expanded_outputs = {
                    "y": (changed_id, "out"),
                    "up": (increased_id, "out"),
                    "down": (decreased_id, "out"),
                }
                slot_map = {}
                kind = BlockKind.NUMERIC_CHANGED
            elif class_name == "Buildings.Controls.OBC.CDL.Reals.Line":
                append_primary = False
                delta_f_id = unique_id(f"{block_id}_delta_f", "DeltaF")
                delta_x_id = unique_id(f"{block_id}_delta_x", "DeltaX")
                slope_id = unique_id(f"{block_id}_slope", "Slope")
                slope_x2_id = unique_id(f"{block_id}_slope_x2", "SlopeX2")
                intercept_id = unique_id(f"{block_id}_intercept", "Intercept")
                scaled_id = unique_id(f"{block_id}_scaled", "Scaled")
                output_block_id = unique_id(f"{block_id}_result", "Line")
                blocks.extend(
                    [
                        Block(id=delta_f_id, kind=BlockKind.SUBTRACT, label=f"{label} Δf"),
                        Block(id=delta_x_id, kind=BlockKind.SUBTRACT, label=f"{label} Δx"),
                        Block(id=slope_id, kind=BlockKind.DIVIDE, label=f"{label} slope"),
                        Block(
                            id=slope_x2_id,
                            kind=BlockKind.MULTIPLY,
                            label=f"{label} slope·x2",
                        ),
                        Block(
                            id=intercept_id,
                            kind=BlockKind.SUBTRACT,
                            label=f"{label} intercept",
                        ),
                        Block(id=scaled_id, kind=BlockKind.MULTIPLY, label=f"{label} b·x"),
                        Block(id=output_block_id, kind=BlockKind.ADD, label=label),
                    ]
                )
                links.extend(
                    [
                        Link(source=delta_f_id, target=slope_id, target_slot="a"),
                        Link(source=delta_x_id, target=slope_id, target_slot="b"),
                        Link(source=slope_id, target=slope_x2_id, target_slot="a"),
                        Link(source=slope_id, target=scaled_id, target_slot="a"),
                        Link(source=slope_x2_id, target=intercept_id, target_slot="b"),
                        Link(source=intercept_id, target=output_block_id, target_slot="a"),
                        Link(source=scaled_id, target=output_block_id, target_slot="b"),
                    ]
                )
                expanded_inputs = {
                    "x1": [(delta_x_id, "b")],
                    "f1": [(delta_f_id, "b")],
                    "x2": [(delta_x_id, "a"), (slope_x2_id, "b")],
                    "f2": [(delta_f_id, "a"), (intercept_id, "a")],
                    "u": [],
                }
                limit_below = parameters.get("limitBelow", True)
                limit_above = parameters.get("limitAbove", True)
                if not isinstance(limit_below, bool) or not isinstance(limit_above, bool):
                    raise CxfImportError(f"{label} line limits must be Boolean parameters")
                limited_source: tuple[str, str] | None = None
                if limit_below:
                    lower_id = unique_id(f"{block_id}_lower_limit", "LowerLimit")
                    blocks.append(
                        Block(id=lower_id, kind=BlockKind.MAXIMUM, label=f"{label} lower limit")
                    )
                    expanded_inputs["x1"].append((lower_id, "a"))
                    expanded_inputs["u"].append((lower_id, "b"))
                    limited_source = (lower_id, "out")
                if limit_above:
                    upper_id = unique_id(f"{block_id}_upper_limit", "UpperLimit")
                    blocks.append(
                        Block(id=upper_id, kind=BlockKind.MINIMUM, label=f"{label} upper limit")
                    )
                    expanded_inputs["x2"].append((upper_id, "a"))
                    if limited_source is None:
                        expanded_inputs["u"].append((upper_id, "b"))
                    else:
                        links.append(
                            Link(
                                source=limited_source[0],
                                source_slot=limited_source[1],
                                target=upper_id,
                                target_slot="b",
                            )
                        )
                    limited_source = (upper_id, "out")
                if limited_source is None:
                    expanded_inputs["u"].append((scaled_id, "b"))
                else:
                    links.append(
                        Link(
                            source=limited_source[0],
                            source_slot=limited_source[1],
                            target=scaled_id,
                            target_slot="b",
                        )
                    )
                slot_map = {}
                kind = BlockKind.ADD
            elif class_name == "Buildings.Controls.OBC.CDL.Reals.PID":
                kind = BlockKind.PID_WITH_RESET
                reset_id = unique_id(f"{block_id}_reset_false", "ResetFalse")
                blocks.append(
                    Block(
                        id=reset_id,
                        kind=BlockKind.BOOLEAN_CONST,
                        label=f"{label} reset disabled",
                        config={"value": False},
                    )
                )
                links.append(Link(source=reset_id, target=block_id, target_slot="trigger"))
                slot_map = {"u_s": "setpoint", "u_m": "measurement"}
                config = _pid_config(parameters, label, with_reset=False)
            elif class_name == "Buildings.Controls.OBC.CDL.Reals.PIDWithReset":
                kind = BlockKind.PID_WITH_RESET
                slot_map = {
                    "u_s": "setpoint",
                    "u_m": "measurement",
                    "trigger": "trigger",
                }
                config = _pid_config(parameters, label, with_reset=True)
            elif class_name in PID_WITH_ENABLE_CLASSES:
                # Preserve the pinned composite exactly instead of introducing a
                # second controller recurrence: while disabled its setpoint is
                # replaced with the measurement, the rising enable edge resets
                # PIDWithReset, and a final switch emits y_neutral.
                append_primary = False
                input_switch_id = unique_id(f"{block_id}_input_switch", "InputSwitch")
                pid_id = unique_id(f"{block_id}_pid", "PidWithReset")
                output_switch_id = unique_id(f"{block_id}_output_switch", "OutputSwitch")
                neutral_id = unique_id(f"{block_id}_neutral", "Neutral")
                pid_config = _pid_config(parameters, label, with_reset=True)
                neutral = _numeric_parameter(
                    parameters,
                    label,
                    "y_neutral",
                    _numeric_parameter(parameters, label, "y_reset", 0.0),
                )
                blocks.extend(
                    [
                        Block(
                            id=input_switch_id,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=f"{label} enabled setpoint",
                        ),
                        Block(
                            id=pid_id,
                            kind=BlockKind.PID_WITH_RESET,
                            label=f"{label} PID with reset",
                            config=pid_config,
                        ),
                        Block(
                            id=neutral_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"{label} disabled output",
                            config={"value": neutral},
                        ),
                        Block(
                            id=output_switch_id,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=label,
                        ),
                    ]
                )
                links.extend(
                    [
                        Link(
                            source=input_switch_id,
                            target=pid_id,
                            target_slot="setpoint",
                        ),
                        Link(
                            source=neutral_id,
                            target=output_switch_id,
                            target_slot="when_false",
                        ),
                    ]
                )
                enabled_output_id = pid_id
                enable_targets = [
                    (input_switch_id, "selector"),
                    (pid_id, "trigger"),
                    (output_switch_id, "selector"),
                ]
                if pid_config["controller_type"] in {"PI", "PID"}:
                    # Modelica reinit is visible in the same event instant. The
                    # scan-oriented PID recurrence commits its reset state for
                    # the next evaluation, so select y_reset on the rising edge
                    # to preserve the source-level output contract as well.
                    rising_id = unique_id(f"{block_id}_enable_edge", "EnableEdge")
                    reset_id = unique_id(f"{block_id}_reset_value", "ResetValue")
                    reset_switch_id = unique_id(f"{block_id}_reset_switch", "ResetOutputSwitch")
                    blocks.extend(
                        [
                            Block(
                                id=rising_id,
                                kind=BlockKind.ONE_SHOT,
                                label=f"{label} enable edge",
                                config={"initial": False},
                            ),
                            Block(
                                id=reset_id,
                                kind=BlockKind.NUMERIC_CONST,
                                label=f"{label} reset output",
                                config={"value": pid_config["y_reset"]},
                            ),
                            Block(
                                id=reset_switch_id,
                                kind=BlockKind.NUMERIC_SWITCH,
                                label=f"{label} same-event reset",
                            ),
                        ]
                    )
                    links.extend(
                        [
                            Link(
                                source=rising_id,
                                target=reset_switch_id,
                                target_slot="selector",
                            ),
                            Link(
                                source=reset_id,
                                target=reset_switch_id,
                                target_slot="when_true",
                            ),
                            Link(
                                source=pid_id,
                                target=reset_switch_id,
                                target_slot="when_false",
                            ),
                        ]
                    )
                    enable_targets.append((rising_id, "in"))
                    enabled_output_id = reset_switch_id
                links.append(
                    Link(
                        source=enabled_output_id,
                        target=output_switch_id,
                        target_slot="when_true",
                    )
                )
                expanded_inputs = {
                    "u_s": [(input_switch_id, "when_true")],
                    "u_m": [
                        (input_switch_id, "when_false"),
                        (pid_id, "measurement"),
                    ],
                    "uEna": enable_targets,
                }
                expanded_outputs = {"y": (output_switch_id, "out")}
                output_block_id = output_switch_id
                slot_map = {}
                kind = BlockKind.PID_WITH_RESET
            elif class_name == TRIM_AND_RESPOND_CLASS:
                hold_enabled = parameters.get("have_hol", False)
                if not isinstance(hold_enabled, bool):
                    raise CxfImportError(f"{label} have_hol must be Boolean")
                kind = (
                    BlockKind.TRIM_AND_RESPOND_HOLD if hold_enabled else BlockKind.TRIM_AND_RESPOND
                )
                slot_map = {
                    "numOfReq": "request_count",
                    "uDevSta": "device_on",
                }
                if hold_enabled:
                    slot_map["uHol"] = "hold"
                config = {
                    "initial_setpoint": _numeric_parameter(parameters, label, "iniSet", 0.0),
                    "minimum_setpoint": _numeric_parameter(parameters, label, "minSet", 0.0),
                    "maximum_setpoint": _numeric_parameter(parameters, label, "maxSet", 1.0),
                    "delay_seconds": _numeric_parameter(parameters, label, "delTim", 0.0),
                    "sample_period_seconds": _numeric_parameter(
                        parameters, label, "samplePeriod", 120.0
                    ),
                    "ignored_requests": _numeric_parameter(parameters, label, "numIgnReq", 0.0),
                    "trim_amount": _numeric_parameter(parameters, label, "triAmo", 0.1),
                    "respond_amount": _numeric_parameter(parameters, label, "resAmo", -0.2),
                    "maximum_response": _numeric_parameter(parameters, label, "maxRes", -0.6),
                    "hold_enabled": hold_enabled,
                }
                if hold_enabled:
                    config["hold_duration_seconds"] = _numeric_parameter(
                        parameters, label, "dtHol", 0.0
                    )
            elif class_name in INITIALIZATION_CLASSES:
                initial = parameters.get("yIni", False)
                if not isinstance(initial, bool):
                    raise CxfImportError(f"{label} yIni must be Boolean")
                kind = BlockKind.BOOLEAN_INITIALIZATION
                slot_map = {"u": "in"}
                config = {
                    "initial": initial,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.Utilities.Initialization"
                    ),
                }
            else:  # guarded by inspect; retained as defense in depth
                raise CxfImportError(f"unsupported CDL class: {class_name}")

            if append_primary:
                blocks.append(
                    Block(
                        id=block_id,
                        kind=kind,
                        label=label,
                        config=config,
                        x=(index % 6) * 180,
                        y=(index // 6) * 120,
                    )
                )
            for connector_id, connector_name in zip(component_inputs, input_names, strict=True):
                targets = expanded_inputs.get(connector_name)
                if targets is not None:
                    input_ports[connector_id] = targets
                    continue
                if connector_name not in slot_map:
                    raise CxfImportError(f"{class_name} input {connector_name!r} has no lowering")
                input_ports[connector_id] = [(block_id, slot_map[connector_name])]
            for connector_id in output_ids:
                connector_name = _local_name(connector_id)
                output_ports[connector_id] = expanded_outputs.get(
                    connector_name,
                    (output_block_id, "out"),
                )

        adjacency: dict[str, set[str]] = {}
        for node in nodes:
            node_id = node.get("@id")
            if not isinstance(node_id, str):
                continue
            for connected in _refs(node, "S231:isConnectedTo"):
                adjacency.setdefault(node_id, set()).add(connected)
                adjacency.setdefault(connected, set()).add(node_id)

        for source_port, source in output_ports.items():
            for target_port in sorted(adjacency.get(source_port, set())):
                targets = input_ports.get(target_port)
                if targets is None:
                    if target_port in output_ports:
                        continue
                    raise CxfImportError(f"connection target has no lowered input: {target_port}")
                for target in targets:
                    links.append(
                        Link(
                            source=source[0],
                            source_slot=source[1],
                            target=target[0],
                            target_slot=target[1],
                        )
                    )

        current_origin = None
        graph_name = unique_id(str(coverage["root_label"]), "CxfProgram")
        used_ids.remove(graph_name)
        return ControlGraph(
            name=graph_name,
            blocks=blocks,
            links=links,
            metadata={
                "source": "ASHRAE-231P-CXF",
                "source_sha256": coverage["source_sha256"],
                "lowering": self.mapping_version,
                "coverage": coverage,
                "block_origins": dict(sorted(origins.items())),
            },
        )
