from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.simulator import GraphInterpreter


class AixocatError(ValueError):
    """Raised when a pinned AixOCAT source cannot be admitted exactly."""


_VAR_SECTION = re.compile(
    r"(?ms)^\s*(?P<section>VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT)"
    r"(?:[ \t]+[A-Z_]+)*[ \t]*\r?\n(?P<body>.*?)^\s*END_VAR\s*$"
)
_POU_HEADER = re.compile(
    r"(?im)^\s*(?P<kind>FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*:\s*(?P<return_type>[A-Za-z_][A-Za-z0-9_]*))?"
)
_BLOCK_COMMENT = re.compile(r"\(\*.*?\*\)", re.DOTALL)
_LINE_COMMENT = re.compile(r"//.*?$", re.MULTILINE)

_TRANSLATABLE = {
    "oscat.automation.MANUAL",
    "oscat.signal_processing.SCALE",
    "oscat.automation.INTERLOCK",
    "oscat.control.DEAD_BAND",
    "oscat.control.DEAD_ZONE",
    "hydronic.components.FC_HeatingCurve",
}


def _strip_comments(value: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", value))


def _normalized_code(value: str) -> str:
    return re.sub(r"\s+", "", _strip_comments(value)).lower()


class AixocatLibrary:
    """Allowlisted TwinCAT Structured Text patterns from the MIT AixOCAT tree.

    This is intentionally not a general IEC 61131-3 compiler. Every executable
    lowering is bound to a named, inspected source pattern and is rejected if
    the source semantics no longer match the adapter.
    """

    def __init__(self, root: Path = Path(".vendor/aixocat")):
        self.root = root.resolve()

    def catalog(self) -> dict[str, Any]:
        patterns = list(self._patterns().values())
        return {
            "schema": "bactalk.aixocat-library/v1",
            "source": "RWTH-EBC AixOCAT",
            "license": "MIT",
            "pattern_count": len(patterns),
            "group_counts": dict(
                sorted(Counter(item["group"] for item in patterns).items())
            ),
            "translatable_count": sum(item["translatable"] for item in patterns),
            "patterns": patterns,
            "scope": (
                "Pinned IEC 61131-3/TwinCAT control references and explicitly mapped "
                "Niagara-neutral patterns; not a general Structured Text compiler"
            ),
        }

    def inspect(self, pattern_id: str) -> dict[str, Any]:
        pattern = self._patterns().get(pattern_id)
        if pattern is None:
            raise KeyError(pattern_id)
        parsed = self._parse(self.root / pattern["relative_path"])
        return {
            "schema": "bactalk.aixocat-pattern/v1",
            "pattern": pattern,
            "declaration": parsed["declaration"],
            "implementation": parsed["implementation"],
            "inputs": parsed["inputs"],
            "outputs": parsed["outputs"],
            "return_type": parsed["return_type"],
            "capabilities": parsed["capabilities"],
        }

    def translate(
        self, pattern_id: str, *, parameters: dict[str, float] | None = None
    ) -> dict[str, Any]:
        pattern = self._patterns().get(pattern_id)
        if pattern is None:
            raise KeyError(pattern_id)
        if pattern_id not in _TRANSLATABLE:
            raise AixocatError(
                f"{pattern_id} is cataloged source, but has no exact BACTalk lowering"
            )
        parsed = self._parse(self.root / pattern["relative_path"])
        supplied = parameters or {}
        if pattern_id == "oscat.signal_processing.SCALE":
            if supplied:
                raise AixocatError("SCALE has no compile-time specialization parameters")
            self._require_code(parsed, "scale:=limit(mn,x*k+o,mx);")
            graph = self._scale_graph(pattern)
            vectors = [
                ({"X": 2.0, "K": 3.0, "O": 1.0, "MX": 5.0, "MN": 0.0}, 5.0),
                ({"X": -2.0, "K": 3.0, "O": 1.0, "MX": 5.0, "MN": 0.0}, 0.0),
            ]
            verification = self._verify_numeric(graph, "SCALE", vectors)
            specialization: dict[str, Any] = {}
        elif pattern_id == "hydronic.components.FC_HeatingCurve":
            if supplied:
                raise AixocatError(
                    "FC_HeatingCurve has no compile-time specialization parameters"
                )
            self._require_code(
                parsed, "fc_heatingcurve:=fslope*ftempamb+foffset;"
            )
            graph = self._heating_curve_graph(pattern)
            vectors = [
                ({"fTempAmb": -10.0, "fSlope": -1.0, "fOffset": 35.0}, 45.0),
                ({"fTempAmb": 10.0, "fSlope": -1.0, "fOffset": 35.0}, 25.0),
            ]
            verification = self._verify_numeric(graph, "FC_HeatingCurve", vectors)
            specialization = {}
        elif pattern_id == "oscat.control.DEAD_BAND":
            if supplied:
                raise AixocatError("DEAD_BAND has no compile-time specialization parameters")
            self._require_code(
                parsed,
                "ifx>lthendead_band:=x-l;elsifx<-lthendead_band:=x+l;"
                "elsedead_band:=0.0;end_if;",
            )
            graph = self._dead_band_graph(pattern)
            verification = self._verify_numeric(
                graph,
                "DEAD_BAND",
                [
                    ({"X": 5.0, "L": 2.0}, 3.0),
                    ({"X": -5.0, "L": 2.0}, -3.0),
                    ({"X": 1.0, "L": 2.0}, 0.0),
                ],
            )
            specialization = {}
        elif pattern_id == "oscat.control.DEAD_ZONE":
            if supplied:
                raise AixocatError("DEAD_ZONE has no compile-time specialization parameters")
            self._require_code(
                parsed,
                "ifabs(x)>lthendead_zone:=x;elsedead_zone:=0.0;end_if;",
            )
            graph = self._dead_zone_graph(pattern)
            verification = self._verify_numeric(
                graph,
                "DEAD_ZONE",
                [
                    ({"X": 5.0, "L": 2.0}, 5.0),
                    ({"X": -5.0, "L": 2.0}, -5.0),
                    ({"X": 1.0, "L": 2.0}, 0.0),
                ],
            )
            specialization = {}
        elif pattern_id == "oscat.automation.MANUAL":
            if supplied:
                raise AixocatError("MANUAL has no compile-time specialization parameters")
            self._require_code(parsed, "manual:=notoffand(inoron);")
            graph = self._manual_graph(pattern)
            verification = self._verify_boolean(
                graph,
                "MANUAL",
                [
                    ({"IN": False, "ON": False, "OFF": False}, False),
                    ({"IN": False, "ON": True, "OFF": False}, True),
                    ({"IN": True, "ON": False, "OFF": True}, False),
                ],
            )
            specialization = {}
        else:  # oscat.automation.INTERLOCK
            if set(supplied) != {"TL_seconds"}:
                raise AixocatError(
                    "INTERLOCK requires exactly one TL_seconds specialization parameter"
                )
            dead_time = supplied["TL_seconds"]
            if isinstance(dead_time, bool) or not isinstance(dead_time, (int, float)):
                raise AixocatError("INTERLOCK TL_seconds must be numeric")
            if not 0 <= dead_time <= 86_400:
                raise AixocatError("INTERLOCK TL_seconds must be between 0 and 86400")
            self._require_code(
                parsed,
                "t1(in:=i1,pt:=tl);t2(in:=i2,pt:=tl);"
                "q1:=i1andnott2.q;q2:=i2andnott1.q;",
            )
            graph = self._interlock_graph(pattern, float(dead_time))
            verification = self._verify_interlock(graph, float(dead_time))
            specialization = {
                "TL_seconds": float(dead_time),
                "reason": (
                    "Niagara BooleanDelay timing is a component property, so AixOCAT's "
                    "runtime TIME input is frozen per generated instance"
                ),
            }
        return {
            "schema": "bactalk.aixocat-translation/v1",
            "pattern": pattern,
            "graph": graph.model_dump(mode="json"),
            "verification": verification,
            "specialization": specialization,
            "niagara_compilable": True,
            "runtime_qualified": False,
        }

    @staticmethod
    def _require_code(parsed: dict[str, Any], expected: str) -> None:
        actual = _normalized_code(parsed["implementation"])
        if actual != expected:
            raise AixocatError(
                "pinned AixOCAT implementation no longer matches its reviewed lowering"
            )

    @staticmethod
    def _block(
        block_id: str, kind: BlockKind, label: str, **config: float | bool
    ) -> Block:
        return Block(id=block_id, kind=kind, label=label, config=config)

    def _scale_graph(self, pattern: dict[str, Any]) -> ControlGraph:
        blocks = [
            self._block(name, BlockKind.NUMERIC_INPUT, name, default=0.0)
            for name in ("X", "K", "O", "MX", "MN")
        ]
        blocks.extend(
            [
                self._block("Product", BlockKind.MULTIPLY, "X multiplied by K"),
                self._block("Offset", BlockKind.ADD, "Scaled value plus offset"),
                self._block("LowLimit", BlockKind.MAXIMUM, "Lower limit"),
                self._block("HighLimit", BlockKind.MINIMUM, "Upper limit"),
                self._block("SCALE", BlockKind.NUMERIC_OUTPUT, "SCALE result"),
            ]
        )
        return ControlGraph(
            name="AixocatScale",
            blocks=blocks,
            links=[
                Link(source="X", target="Product", target_slot="a"),
                Link(source="K", target="Product", target_slot="b"),
                Link(source="Product", target="Offset", target_slot="a"),
                Link(source="O", target="Offset", target_slot="b"),
                Link(source="Offset", target="LowLimit", target_slot="a"),
                Link(source="MN", target="LowLimit", target_slot="b"),
                Link(source="LowLimit", target="HighLimit", target_slot="a"),
                Link(source="MX", target="HighLimit", target_slot="b"),
                Link(source="HighLimit", target="SCALE", target_slot="in"),
            ],
            metadata=self._metadata(pattern),
        )

    def _heating_curve_graph(self, pattern: dict[str, Any]) -> ControlGraph:
        return ControlGraph(
            name="AixocatHeatingCurve",
            blocks=[
                self._block("fTempAmb", BlockKind.NUMERIC_INPUT, "Ambient temperature"),
                self._block("fSlope", BlockKind.NUMERIC_INPUT, "Heating-curve slope"),
                self._block("fOffset", BlockKind.NUMERIC_INPUT, "Heating-curve offset"),
                self._block("Product", BlockKind.MULTIPLY, "Slope by ambient temperature"),
                self._block("Sum", BlockKind.ADD, "Heating-curve setpoint"),
                self._block(
                    "FC_HeatingCurve", BlockKind.NUMERIC_OUTPUT, "Heating curve result"
                ),
            ],
            links=[
                Link(source="fSlope", target="Product", target_slot="a"),
                Link(source="fTempAmb", target="Product", target_slot="b"),
                Link(source="Product", target="Sum", target_slot="a"),
                Link(source="fOffset", target="Sum", target_slot="b"),
                Link(source="Sum", target="FC_HeatingCurve", target_slot="in"),
            ],
            metadata=self._metadata(pattern),
        )

    def _interlock_graph(
        self, pattern: dict[str, Any], dead_time: float
    ) -> ControlGraph:
        delay = {
            "on_delay_seconds": 0.0,
            "off_delay_seconds": dead_time,
            "initial": False,
        }
        return ControlGraph(
            name="AixocatInterlock",
            blocks=[
                self._block("I1", BlockKind.BOOLEAN_INPUT, "Interlock request 1"),
                self._block("I2", BlockKind.BOOLEAN_INPUT, "Interlock request 2"),
                Block(id="T1", kind=BlockKind.BOOLEAN_DELAY, label="I1 off delay", config=delay),
                Block(id="T2", kind=BlockKind.BOOLEAN_DELAY, label="I2 off delay", config=delay),
                self._block("NotT1", BlockKind.NOT, "I1 not held"),
                self._block("NotT2", BlockKind.NOT, "I2 not held"),
                self._block("GateQ1", BlockKind.AND, "Request 1 permissive"),
                self._block("GateQ2", BlockKind.AND, "Request 2 permissive"),
                self._block("Q1", BlockKind.BOOLEAN_OUTPUT, "Interlocked output 1"),
                self._block("Q2", BlockKind.BOOLEAN_OUTPUT, "Interlocked output 2"),
            ],
            links=[
                Link(source="I1", target="T1", target_slot="in"),
                Link(source="I2", target="T2", target_slot="in"),
                Link(source="T1", target="NotT1", target_slot="in"),
                Link(source="T2", target="NotT2", target_slot="in"),
                Link(source="I1", target="GateQ1", target_slot="a"),
                Link(source="NotT2", target="GateQ1", target_slot="b"),
                Link(source="I2", target="GateQ2", target_slot="a"),
                Link(source="NotT1", target="GateQ2", target_slot="b"),
                Link(source="GateQ1", target="Q1", target_slot="in"),
                Link(source="GateQ2", target="Q2", target_slot="in"),
            ],
            metadata={
                **self._metadata(pattern),
                "specialization": {"TL_seconds": dead_time},
            },
        )

    def _manual_graph(self, pattern: dict[str, Any]) -> ControlGraph:
        return ControlGraph(
            name="AixocatManual",
            blocks=[
                self._block("IN", BlockKind.BOOLEAN_INPUT, "Automatic input"),
                self._block("ON", BlockKind.BOOLEAN_INPUT, "Manual on"),
                self._block("OFF", BlockKind.BOOLEAN_INPUT, "Manual off"),
                self._block("NotOff", BlockKind.NOT, "Off not asserted"),
                self._block("Requested", BlockKind.OR, "Automatic or manual on"),
                self._block("Permitted", BlockKind.AND, "Manual output permissive"),
                self._block("MANUAL", BlockKind.BOOLEAN_OUTPUT, "Manual result"),
            ],
            links=[
                Link(source="OFF", target="NotOff", target_slot="in"),
                Link(source="IN", target="Requested", target_slot="a"),
                Link(source="ON", target="Requested", target_slot="b"),
                Link(source="NotOff", target="Permitted", target_slot="a"),
                Link(source="Requested", target="Permitted", target_slot="b"),
                Link(source="Permitted", target="MANUAL", target_slot="in"),
            ],
            metadata=self._metadata(pattern),
        )

    def _dead_band_graph(self, pattern: dict[str, Any]) -> ControlGraph:
        return ControlGraph(
            name="AixocatDeadBand",
            blocks=[
                self._block("X", BlockKind.NUMERIC_INPUT, "Input"),
                self._block("L", BlockKind.NUMERIC_INPUT, "Deadband magnitude"),
                self._block("Zero", BlockKind.NUMERIC_CONST, "Zero", value=0.0),
                self._block("NegL", BlockKind.SUBTRACT, "Negative deadband"),
                self._block("Above", BlockKind.GREATER_THAN, "Above positive band"),
                self._block("Below", BlockKind.LESS_THAN, "Below negative band"),
                self._block("Positive", BlockKind.SUBTRACT, "Positive adjusted value"),
                self._block("Negative", BlockKind.ADD, "Negative adjusted value"),
                self._block(
                    "NegativeOrZero", BlockKind.NUMERIC_SWITCH, "Negative band branch"
                ),
                self._block("Select", BlockKind.NUMERIC_SWITCH, "Deadband branch"),
                self._block("DEAD_BAND", BlockKind.NUMERIC_OUTPUT, "Deadband result"),
            ],
            links=[
                Link(source="Zero", target="NegL", target_slot="a"),
                Link(source="L", target="NegL", target_slot="b"),
                Link(source="X", target="Above", target_slot="a"),
                Link(source="L", target="Above", target_slot="b"),
                Link(source="X", target="Below", target_slot="a"),
                Link(source="NegL", target="Below", target_slot="b"),
                Link(source="X", target="Positive", target_slot="a"),
                Link(source="L", target="Positive", target_slot="b"),
                Link(source="X", target="Negative", target_slot="a"),
                Link(source="L", target="Negative", target_slot="b"),
                Link(source="Below", target="NegativeOrZero", target_slot="selector"),
                Link(source="Negative", target="NegativeOrZero", target_slot="when_true"),
                Link(source="Zero", target="NegativeOrZero", target_slot="when_false"),
                Link(source="Above", target="Select", target_slot="selector"),
                Link(source="Positive", target="Select", target_slot="when_true"),
                Link(source="NegativeOrZero", target="Select", target_slot="when_false"),
                Link(source="Select", target="DEAD_BAND", target_slot="in"),
            ],
            metadata=self._metadata(pattern),
        )

    def _dead_zone_graph(self, pattern: dict[str, Any]) -> ControlGraph:
        return ControlGraph(
            name="AixocatDeadZone",
            blocks=[
                self._block("X", BlockKind.NUMERIC_INPUT, "Input"),
                self._block("L", BlockKind.NUMERIC_INPUT, "Dead-zone magnitude"),
                self._block("Zero", BlockKind.NUMERIC_CONST, "Zero", value=0.0),
                self._block(
                    "Nonnegative", BlockKind.GREATER_THAN_OR_EQUAL, "Input is nonnegative"
                ),
                self._block("Negated", BlockKind.SUBTRACT, "Negated input"),
                self._block("Absolute", BlockKind.NUMERIC_SWITCH, "Absolute input"),
                self._block("Outside", BlockKind.GREATER_THAN, "Outside dead zone"),
                self._block("Select", BlockKind.NUMERIC_SWITCH, "Dead-zone branch"),
                self._block("DEAD_ZONE", BlockKind.NUMERIC_OUTPUT, "Dead-zone result"),
            ],
            links=[
                Link(source="X", target="Nonnegative", target_slot="a"),
                Link(source="Zero", target="Nonnegative", target_slot="b"),
                Link(source="Zero", target="Negated", target_slot="a"),
                Link(source="X", target="Negated", target_slot="b"),
                Link(source="Nonnegative", target="Absolute", target_slot="selector"),
                Link(source="X", target="Absolute", target_slot="when_true"),
                Link(source="Negated", target="Absolute", target_slot="when_false"),
                Link(source="Absolute", target="Outside", target_slot="a"),
                Link(source="L", target="Outside", target_slot="b"),
                Link(source="Outside", target="Select", target_slot="selector"),
                Link(source="X", target="Select", target_slot="when_true"),
                Link(source="Zero", target="Select", target_slot="when_false"),
                Link(source="Select", target="DEAD_ZONE", target_slot="in"),
            ],
            metadata=self._metadata(pattern),
        )

    @staticmethod
    def _metadata(pattern: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": "AixOCAT IEC 61131-3 Structured Text",
            "source_id": pattern["id"],
            "source_sha256": pattern["source_sha256"],
            "license": "MIT",
            "lowering": "bactalk-aixocat-lowering/v1",
        }

    @staticmethod
    def _verify_numeric(
        graph: ControlGraph,
        output: str,
        vectors: list[tuple[dict[str, float | bool], float]],
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for inputs, expected in vectors:
            actual = GraphInterpreter(graph).evaluate(inputs)[output]
            passed = abs(float(actual) - expected) <= 1e-9
            results.append(
                {"inputs": inputs, "expected": expected, "actual": actual, "passed": passed}
            )
        if not all(row["passed"] for row in results):
            raise AixocatError("translated AixOCAT numeric vectors failed")
        return {"passed": True, "vectors": results}

    @staticmethod
    def _verify_boolean(
        graph: ControlGraph,
        output: str,
        vectors: list[tuple[dict[str, float | bool], bool]],
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for inputs, expected in vectors:
            actual = GraphInterpreter(graph).evaluate(inputs)[output]
            passed = isinstance(actual, bool) and actual is expected
            results.append(
                {"inputs": inputs, "expected": expected, "actual": actual, "passed": passed}
            )
        if not all(row["passed"] for row in results):
            raise AixocatError("translated AixOCAT Boolean vectors failed")
        return {"passed": True, "vectors": results}

    @staticmethod
    def _verify_interlock(graph: ControlGraph, dead_time: float) -> dict[str, Any]:
        interpreter = GraphInterpreter(graph)
        rows: list[dict[str, Any]] = []
        timeline = [
            ({"I1": False, "I2": False}, 1.0),
            ({"I1": True, "I2": False}, 1.0),
            ({"I1": False, "I2": True}, 1.0),
        ]
        # Continue longer than the specialized off-delay to prove transfer.
        timeline.extend(
            [({"I1": False, "I2": True}, 1.0)] * (int(dead_time) + 2)
        )
        for inputs, step in timeline:
            values = interpreter.evaluate(inputs, step_seconds=step)
            row = {"inputs": inputs, "Q1": values["Q1"], "Q2": values["Q2"]}
            if row["Q1"] and row["Q2"]:
                raise AixocatError("translated INTERLOCK energized both outputs")
            rows.append(row)
        if dead_time == 0 and not rows[2]["Q2"]:
            raise AixocatError("zero-delay INTERLOCK did not transfer immediately")
        if dead_time > 0 and (rows[2]["Q2"] or not rows[-1]["Q2"]):
            raise AixocatError("INTERLOCK dead-time verification failed")
        return {"passed": True, "timeline": rows}

    def _patterns(self) -> dict[str, dict[str, Any]]:
        if not (self.root / "LICENSE").is_file():
            raise FileNotFoundError("AixOCAT source library is not installed")
        patterns: dict[str, dict[str, Any]] = {}
        for path in sorted(self.root.rglob("*.TcPOU")):
            if ".git" in path.parts:
                continue
            parsed = self._parse(path)
            relative = path.relative_to(self.root)
            group = self._group(relative)
            pattern_id = f"{group}.{parsed['name']}"
            if pattern_id in patterns:
                raise AixocatError(f"duplicate AixOCAT pattern id: {pattern_id}")
            patterns[pattern_id] = {
                "id": pattern_id,
                "name": parsed["name"],
                "kind": parsed["kind"].lower(),
                "group": group,
                "relative_path": relative.as_posix(),
                "source_sha256": parsed["source_sha256"],
                "source_bytes": parsed["source_bytes"],
                "input_count": len(parsed["inputs"]),
                "output_count": len(parsed["outputs"]) + bool(parsed["return_type"]),
                "capabilities": parsed["capabilities"],
                "translatable": pattern_id in _TRANSLATABLE,
            }
        return patterns

    @staticmethod
    def _group(relative: Path) -> str:
        value = relative.as_posix()
        if value.startswith("OSCAT/"):
            category = relative.parent.name.lower().replace(" ", "_")
            return f"oscat.{category}"
        if "HeatPumpTestBenchControl" in value:
            parts = relative.parts
            index = parts.index("POUs")
            category = "_".join(parts[index + 1 : -1]).lower()
            return f"heat_pump.{category}"
        if "HeatSupplyCircle" in value:
            return "hydronic.components"
        if "ERC_TestHall/CCA" in value:
            return "test_hall.control"
        if "ERC_TestHall/Components" in value:
            return "test_hall.components"
        raise AixocatError(f"unclassified allowlisted AixOCAT source: {relative}")

    @staticmethod
    def _parse(path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        if len(raw) > 2_000_000:
            raise AixocatError(f"AixOCAT source exceeds admission limit: {path.name}")
        text = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise AixocatError(f"AixOCAT source contains forbidden XML declarations: {path.name}")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise AixocatError(f"invalid TwinCAT XML in {path.name}: {exc}") from exc
        pou = root.find("./POU")
        declaration_node = root.find("./POU/Declaration")
        implementation_node = root.find("./POU/Implementation/ST")
        if pou is None or declaration_node is None or implementation_node is None:
            raise AixocatError(f"incomplete TwinCAT POU source: {path.name}")
        declaration = declaration_node.text or ""
        implementation = implementation_node.text or ""
        header = _POU_HEADER.search(declaration)
        if header is None:
            raise AixocatError(f"missing POU declaration header: {path.name}")
        if pou.get("Name") != header.group("name"):
            raise AixocatError(f"POU name mismatch in {path.name}")
        sections: dict[str, list[dict[str, str | None]]] = {
            "VAR_INPUT": [],
            "VAR_OUTPUT": [],
            "VAR_IN_OUT": [],
        }
        for match in _VAR_SECTION.finditer(declaration):
            sections[match.group("section")].extend(
                AixocatLibrary._variables(match.group("body"), path.name)
            )
        joined = f"{declaration}\n{implementation}".upper()
        capabilities = sorted(
            name
            for name, pattern in {
                "external_network": r"\b(?:ADS|BACNET|MODBUS|MQTT|TCP|UDP)[A-Z0-9_]*\b",
                "filesystem": r"\b(?:FILE|FOPEN|FCLOSE|FREAD|FWRITE)[A-Z0-9_]*\b",
                "hardware_io": r"%[IQM][XBWDL]?\d",
                "timers": r"\b(?:TON|TOF|TP)\b",
                "wall_clock": r"\b(?:RTC|DT_TO_|T_PLC_|GETSYSTEMTIME)\b",
            }.items()
            if re.search(pattern, joined)
        )
        return {
            "name": header.group("name"),
            "kind": header.group("kind"),
            "return_type": header.group("return_type"),
            "declaration": declaration,
            "implementation": implementation,
            "inputs": sections["VAR_INPUT"],
            "outputs": sections["VAR_OUTPUT"],
            "in_out": sections["VAR_IN_OUT"],
            "capabilities": capabilities,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "source_bytes": len(raw),
        }

    @staticmethod
    def _variables(body: str, filename: str) -> list[dict[str, str | None]]:
        variables: list[dict[str, str | None]] = []
        for statement in _strip_comments(body).split(";"):
            statement = statement.strip()
            if not statement:
                continue
            assignment = statement.split(":=", 1)
            declaration = assignment[0].strip()
            default = assignment[1].strip() if len(assignment) == 2 else None
            if ":" not in declaration:
                raise AixocatError(f"unparsed variable declaration in {filename}: {statement}")
            names, type_name = declaration.split(":", 1)
            type_name = type_name.strip()
            for name in names.split(","):
                variable = re.fullmatch(
                    r"\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
                    r"(?:\s+AT\s+(?P<address>\S+))?\s*",
                    name,
                    re.IGNORECASE,
                )
                if variable is None:
                    raise AixocatError(
                        f"unsupported variable name in {filename}: {name.strip()}"
                    )
                normalized = variable.group("name")
                variables.append(
                    {
                        "name": normalized,
                        "type": type_name,
                        "default": default,
                        "address": variable.group("address"),
                    }
                )
        return variables
