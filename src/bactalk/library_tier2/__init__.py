"""Tier 2: every LBNL Guideline 36 controller with a reference (GOAL-NATIVE-BOG.md N8).

A *configuration* is one controller with one complete parameter set (the CDL
parameters LBNL leaves without defaults, plus the variant choices such as the
ventilation standard). Each configuration carries a retained translation and a
retained Open Control Engine reference under this package, so a base install can
build its job, run the four proofs and render ``docs/coverage.md`` without the
vendored toolchain. ``scripts/retain_tier2.py`` regenerates both.

Scenarios are built mechanically from the controller's public interface (N8 step 3,
the protocol's positive/negative/boundary rule applied blindly): a nominal operating
point, one perturbation per input, every operation mode. Expectations are the
reference's end-of-scenario values inside the D3 band, so the suite grades the
translation against LBNL, never against a hand-written guess; adequacy is what the
D4 mutation sample says it is (docs/decisions/010).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

from bactalk.domain import (
    AcceptanceCase,
    ComparisonOperator,
    ControlGraph,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)

SCHEMA_TRANSLATION = "bactalk.retained-library-translation/v1"
SCHEMA_REFERENCE = "bactalk.retained-reference-trace/v1"

# Guideline 36 operation modes (Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes).
OPERATION_MODES = {
    "occupied": 1,
    "coolDown": 2,
    "setUp": 3,
    "warmUp": 4,
    "setBack": 5,
    "freezeProtection": 6,
    "unoccupied": 7,
}

_TYPES = "Buildings.Controls.OBC.ASHRAE.G36.Types"
ASHRAE62_1 = f"{_TYPES}.VentilationStandard.ASHRAE62_1"
TITLE24 = f"{_TYPES}.VentilationStandard.California_Title_24"
ASHRAE90_1 = f"{_TYPES}.EnergyStandard.ASHRAE90_1"
ENERGY_TITLE24 = f"{_TYPES}.EnergyStandard.California_Title_24"

# The same box LBNL's own validation uses for the reheat controller (Tier 1), so the
# terminal-unit family shares one physical design and differs only in its logic.
_BOX = {
    "VAreBreZon_flow": 0.014,
    "VAreMin_flow": 0.014,
    "VCooMax_flow": 0.472,
    "VMin_flow": 0.094,
    "VOccMin_flow": 0.024,
    "VPopBreZon_flow": 0.024,
}
_DUAL = {**_BOX, "VHeaMax_flow": 0.236}

SCANS = 45
SCAN_SECONDS = 60.0


@dataclass(frozen=True)
class Configuration:
    id: str
    controller_id: str
    family: str
    variant: str
    parameters: dict[str, Any]
    description: str
    execution_profile: str = "host_tick_v1"
    tier: str = "2"
    notes: tuple[str, ...] = field(default_factory=tuple)
    source: str = "release"
    """Which locked Modelica Buildings checkout translates it: ``release`` (the tagged
    release every G36 airside controller uses) or ``plants`` (LBNL master, for the G36
    chiller-plant controllers no release carries yet; ops/stack.lock.json)."""
    nominal: dict[str, Any] = field(default_factory=dict)
    """Nominal operating point overrides for this configuration's inputs. The shared
    tables below suit the airside controllers; a plant sequence needs its own (plant
    scheduled on, pumps proven, condenser water at design) or every mechanical
    scenario sits in the disabled state and exercises nothing."""

    @property
    def translation_file(self) -> str:
        return f"{self.id}.json"


def _terminal(unit: str, variant: str, params: dict[str, Any], extra: str = "") -> Configuration:
    return Configuration(
        id=f"tu-{unit.lower()}-{variant.lower().replace('_', '-')}",
        controller_id=f"TerminalUnits.{unit}.Controller",
        family="TerminalUnits",
        variant=variant,
        parameters=params,
        description=f"{unit} terminal unit, {variant.replace('_', ' ')}{extra}",
    )


CONFIGURATIONS: tuple[Configuration, ...] = (
    Configuration(
        "ahu-singlezone-vav-ashrae",
        "AHUs.SingleZone.VAV.Controller",
        "AHUs",
        "ASHRAE90_1+ASHRAE62_1",
        {"eneStd": ASHRAE90_1, "venStd": ASHRAE62_1},
        "Single-zone VAV AHU, ASHRAE 90.1 economizer and 62.1 ventilation",
    ),
    Configuration(
        "ahu-singlezone-vav-title24",
        "AHUs.SingleZone.VAV.Controller",
        "AHUs",
        "Title24",
        {"eneStd": ENERGY_TITLE24, "venStd": TITLE24},
        "Single-zone VAV AHU, California Title 24 economizer and ventilation",
    ),
    Configuration(
        "fcu-controller",
        "FanCoilUnits.Controller",
        "FanCoilUnits",
        "default",
        {"TSupSet_max": 303.15, "TSupSet_min": 285.15},
        "Fan coil unit with supply temperature limits 12 °C to 30 °C",
    ),
    _terminal("CoolingOnly", "ASHRAE62_1", {**_BOX, "venStd": ASHRAE62_1}),
    _terminal("CoolingOnly", "Title24", {**_BOX, "venStd": TITLE24}),
    _terminal("SeriesFanCVF", "ASHRAE62_1", {**_BOX, "venStd": ASHRAE62_1}),
    _terminal("SeriesFanVVF", "ASHRAE62_1", {**_BOX, "maxRat": 0.5, "venStd": ASHRAE62_1}),
    _terminal("ParallelFanCVF", "ASHRAE62_1", {**_BOX, "venStd": ASHRAE62_1}),
    _terminal(
        "ParallelFanVVF", "ASHRAE62_1", {**_BOX, "maxRat": 0.5, "minRat": 0.1, "venStd": ASHRAE62_1}
    ),
    _terminal(
        "DualDuctSnapActing",
        "ASHRAE62_1_dual_sensor",
        {**_DUAL, "have_duaSen": True, "venStd": ASHRAE62_1},
        ", discharge sensors on both ducts",
    ),
    _terminal(
        "DualDuctSnapActing",
        "ASHRAE62_1_single_sensor",
        {**_DUAL, "have_duaSen": False, "venStd": ASHRAE62_1},
        ", one discharge sensor",
    ),
    _terminal("DualDuctColdDuctMin", "ASHRAE62_1", {**_DUAL, "venStd": ASHRAE62_1}),
    _terminal("DualDuctMixConDischargeSensor", "ASHRAE62_1", {**_DUAL, "venStd": ASHRAE62_1}),
    _terminal("DualDuctMixConInletSensor", "ASHRAE62_1", {**_DUAL, "venStd": ASHRAE62_1}),
    Configuration(
        "zone-setpoints-occ-win",
        "ThermalZones.Setpoints",
        "ThermalZones",
        "occupancy+window",
        {"have_occSen": True, "have_winSen": True},
        "Zone temperature setpoints with occupancy and window sensors",
    ),
    Configuration(
        "zone-control-loops",
        "ThermalZones.ControlLoops",
        "ThermalZones",
        "default",
        {},
        "Zone heating and cooling loops",
    ),
    Configuration(
        "zone-alarms", "ThermalZones.Alarms", "ThermalZones", "default", {}, "Zone alarms"
    ),
    Configuration(
        "zone-states", "ThermalZones.ZoneStates", "ThermalZones", "default", {}, "Zone states"
    ),
    Configuration(
        "vent-ashrae62-1-setpoints",
        "VentilationZones.ASHRAE62_1.Setpoints",
        "VentilationZones",
        "ASHRAE62_1",
        {"VAreBreZon_flow": 0.014, "VMin_flow": 0.094, "VPopBreZon_flow": 0.024},
        "ASHRAE 62.1 zone ventilation setpoints",
    ),
    Configuration(
        "vent-title24-setpoints",
        "VentilationZones.Title24.Setpoints",
        "VentilationZones",
        "Title24",
        {"VAreMin_flow": 0.014, "VMin_flow": 0.094, "VOccMin_flow": 0.024},
        "California Title 24 zone ventilation setpoints",
    ),
    Configuration(
        "zone-group-status",
        "ZoneGroups.GroupStatus",
        "ZoneGroups",
        "default",
        {},
        "Zone group status",
    ),
    Configuration(
        "zone-group-operation-mode",
        "ZoneGroups.OperationMode",
        "ZoneGroups",
        "one zone",
        {"nZon": 1},
        "Zone group operation mode selection for one zone",
    ),
    # --- G36 chiller plant (§5.20), from LBNL master (source "plants"). The design values
    # are LBNL's own validation plant: two 200 kW chillers, two primary pumps, two
    # condenser pumps, two tower cells (Plants/Chillers/Validation/Controller.mo).
    Configuration(
        "chw-plant-enable",
        "Plants.Chillers.Generic.PlantEnable.Enable",
        "Plants.Chillers",
        "default",
        {},
        "Chiller plant enable and disable (schedule, requests, outdoor lockout)",
        source="plants",
        # Scheduled on with two requests at 7 °C outside: the cold move (3 °C) crosses
        # the 4.35 °C lockout, zero requests and the schedule toggle disable it.
        nominal={"TOut": 280.15, "chiPlaReq": 2, "uPlaSchEna": True},
    ),
    Configuration(
        "chw-plant-reset",
        "Plants.Chillers.SetPoints.ChilledWaterPlantReset",
        "Plants.Chillers",
        "default",
        {},
        "Chilled-water plant reset by trim and respond on plant requests",
        source="plants",
        # Four requests against two ignored, one of two pumps proven on.
        nominal={"TChiWatSupResReq": 4, "uChiWatPum__1": True, "uChiWatPum__2": False},
    ),
    Configuration(
        "chw-supply-setpoints",
        "Plants.Chillers.SetPoints.ChilledWaterSupply",
        "Plants.Chillers",
        "one remote dp sensor",
        {"TChiWatSupMin": 278.15, "dpChiWatMax": [10 * 6894.76]},
        "Chilled-water supply temperature and differential pressure setpoints from the plant reset",
        source="plants",
        nominal={"uChiWatPlaRes": 0.5},
    ),
    Configuration(
        "chw-head-pressure",
        "Plants.Chillers.HeadPressure.Controller",
        "Plants.Chillers",
        "Ti 120 s",
        {"Ti": 120.0},
        "Chiller head pressure control (condenser water valve and tower fan limits); "
        "integral time 120 s, since LBNL's 0.5 s default makes the loop flip between "
        "its limits on every 60 s scan",
        source="plants",
        # Head pressure control enabled, 7 °C chilled water, 18 °C condenser return: an
        # 11 K lift just above the 10 K minimum, so the cold move puts the loop to work.
        nominal={
            "TChiWatSup": 280.15,
            "TConWatRet": 291.15,
            "desConWatPumSpe": 0.75,
            "uChiHeaCon": True,
            "uWSE": False,
        },
    ),
    Configuration(
        "chw-minimum-flow-bypass",
        "Plants.Chillers.MinimumFlowBypass.Controller",
        "Plants.Chillers",
        "two chillers",
        {"minFloSet": [0.0089, 0.0089], "Ti": 120.0, "Td": 0.1},
        "Chilled-water minimum flow bypass valve control; integral time 120 s (LBNL's "
        "0.5 s default flips the valve between its limits on every 60 s scan) and Td "
        "0.1 s (the default of 0 is unused by the PI loop but below PIDWithEnable's minimum)",
        source="plants",
        # Pump on, measured flow a little under the 0.0089 m³/s minimum setpoint.
        nominal={"VChiWatSet_flow": 0.0089, "VChiWat_flow": 0.008, "uChiWatPum": True},
    ),
)
CONFIGURATIONS_BY_ID = {item.id: item for item in CONFIGURATIONS}


# --- retained data ------------------------------------------------------------------------


def _read(subpackage: str, filename: str) -> dict[str, Any] | None:
    package = resources.files(__package__)
    resource = (package.joinpath(subpackage) if subpackage else package).joinpath(filename)
    if not resource.is_file():
        return None
    return json.loads(resource.read_text(encoding="utf-8"))


@cache
def retained_translation(config_id: str) -> dict[str, Any]:
    document = _read("translations", CONFIGURATIONS_BY_ID[config_id].translation_file)
    if document is None:
        raise FileNotFoundError(
            f"no retained translation for {config_id}; run scripts/retain_tier2.py"
        )
    return document


@cache
def reference_trace(config_id: str) -> dict[str, Any] | None:
    return _read("references", CONFIGURATIONS_BY_ID[config_id].translation_file)


def coverage_report() -> dict[str, Any] | None:
    """The committed D1–D4 coverage report (``scripts/coverage_report.py``), or None."""

    return _read("", "coverage.json")


def retained_ids() -> list[str]:
    return [item.id for item in CONFIGURATIONS if _read("translations", item.translation_file)]


# --- points and nominal inputs ---------------------------------------------------------------

# Nominal operating point by exact port name, then by prefix; SI units as LBNL uses them.
_NOMINAL_EXACT: dict[str, float | bool | int] = {
    "TZon": 295.15,
    "TCooSet": 297.15,
    "THeaSet": 293.15,
    "TZonCooSet": 297.15,
    "TZonHeaSet": 293.15,
    "TOccCooSet": 297.15,
    "TOccHeaSet": 293.15,
    "TUnoCooSet": 303.15,
    "TUnoHeaSet": 285.15,
    "TSup": 286.15,
    "TSupSet": 286.15,
    "TDis": 288.15,
    "TColSup": 286.15,
    "THotSup": 308.15,
    "TOut": 283.15,
    "TAirSup": 286.15,
    "TAirRet": 296.15,
    "TAirMix": 290.15,
    "TAirOut": 283.15,
    "TCut": 291.15,
    "hOut": 45000.0,
    "hCut": 50000.0,
    "ppmCO2": 600.0,
    "ppmCO2Set": 900.0,
    "VDis_flow": 0.094,
    "VColDucDis_flow": 0.05,
    "VHotDucDis_flow": 0.05,
    "VPri_flow": 0.094,
    "VAdjPopBreZon_flow": 0.024,
    "VAdjAreBreZon_flow": 0.014,
    "VMinOA_flow": 0.03,
    "VOut_flow": 0.5,
    "dpDuc": 250.0,
    "dpBui": 12.0,
    "uOpeMod": OPERATION_MODES["occupied"],
    "uZonPreResReq": 0,
    "uZonTemResReq": 0,
    "u1Fan": True,
    "u1SupFan": True,
    "u1Occ": True,
    "u1Win": True,
    "u1HotPla": True,
    "u1CooPla": True,
    "u1ColDucFan": True,
    "u1HotDucFan": True,
    "uHeaOff": False,
    "u1FreSta": False,
    "u1SofSwiRes": False,
    "u1RelFan": False,
    "oveDamPos": 0,
    "oveFloSet": 0,
    "oveFan": 0,
    "oveCooDamPos": 0,
    "oveHeaDamPos": 0,
    "uCoo": 0.0,
    "uHea": 0.0,
    "uFan": 0.0,
    "uRelFan": 0.0,
    "warUpTim": 1800.0,
    "cooDowTim": 1800.0,
    "tNexOcc": 3600.0,
    "nOcc": 2,
}
_NOMINAL_PREFIX: tuple[tuple[str, float | bool | int], ...] = (
    ("dp", 100.0),
    ("ppm", 600.0),
    ("TSet", 293.15),
    ("T", 293.15),
    ("V", 0.1),
    ("h", 45000.0),
    ("u1", True),
    ("uOpe", 1),
    ("y1", False),
    ("u", 0.0),
)


def nominal_input(name: str, data_type: str) -> float | bool | int:
    if name in _NOMINAL_EXACT:
        value = _NOMINAL_EXACT[name]
    else:
        value = next((v for prefix, v in _NOMINAL_PREFIX if name.startswith(prefix)), 0.0)
    if data_type == "boolean":
        return bool(value)
    if data_type == "integer":
        return int(value)
    return float(value)


def _nominal_for(config_id: str, name: str, data_type: str) -> float | bool | int:
    override = CONFIGURATIONS_BY_ID[config_id].nominal
    if name in override:
        value = override[name]
        if data_type == "boolean":
            return bool(value)
        if data_type == "integer":
            return int(value)
        return float(value)
    return nominal_input(name, data_type)


def _unit_for(name: str, data_type: str) -> str | None:
    if data_type != "numeric":
        return None
    if name.startswith("ppm"):
        return "ppm"
    if name.startswith("dp") or name.startswith("yDp"):
        return "Pa"
    if name.startswith("h") and name[1:2].isupper():
        return "J/kg"
    if name.startswith("T") and name[1:2].isupper():
        return "K"
    if name.startswith("V") and name[1:2].isupper():
        return "m3/s"
    if name.endswith("Tim") or name.startswith("tNex"):
        return "s"
    return None


def _data_type(point: dict[str, Any]) -> str:
    return str(point["data_type"])


def points_for(config_id: str) -> list[PointSpec]:
    translation = retained_translation(config_id)
    points: list[PointSpec] = []
    for point in translation["points"]:
        name = point["name"]
        data_type = _data_type(point)
        is_input = point["source_interface_direction"] == "input"
        default = _nominal_for(config_id, name, data_type) if is_input else point["default"]
        points.append(
            PointSpec(
                name=name,
                label=point["label"],
                data_type=DataType(data_type),
                role=PointRole.SENSOR if is_input else PointRole.COMMAND,
                units=_unit_for(name, data_type),
                default=default,
                required=True,
            )
        )
    return points


def graph_for(config_id: str, points: list[PointSpec]) -> ControlGraph:
    graph = ControlGraph.model_validate(retained_translation(config_id)["typed_ir"])
    defaults = {point.name: point.default for point in points}
    blocks = []
    for block in graph.blocks:
        if block.id in defaults and block.kind.value.endswith("_input"):
            block = block.model_copy(
                update={"config": {**block.config, "default": defaults[block.id]}}
            )
        blocks.append(block)
    return graph.model_copy(update={"blocks": blocks})


def sequence_for(config_id: str) -> SequenceSpec:
    config = CONFIGURATIONS_BY_ID[config_id]
    translation = retained_translation(config_id)
    release = "v13.0.0" if config.source == "release" else "master (plants)"
    return SequenceSpec(
        family="LBNL_G36_CONTROLLER",
        version=(
            f"LBNL Modelica Buildings {release} "
            f"({translation['source']['revision'][:12]}) · retained translation "
            f"cxf {translation['translator']['cxf_source_sha256'][:12]}"
        ),
        library="g36",
        controller_id=config.controller_id,
        execution_profile=translation["execution_profile"],
        parameters=dict(translation["parameters"]),
    )


# --- mechanical scenarios --------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    name: str
    inputs: dict[str, float | bool | int]
    rationale: str


def _perturb(name: str, data_type: str, value: float | bool | int) -> list[tuple[str, Any, str]]:
    """Blind boundary moves for one input: the protocol's positive/negative pair."""

    if data_type == "boolean":
        return [("toggled", not bool(value), "the opposite state")]
    if data_type == "integer":
        if name == "uOpeMod":
            return [
                (mode, index, f"operation mode {mode}")
                for mode, index in OPERATION_MODES.items()
                if index != value
            ]
        return [("plus", int(value) + 2, "two more"), ("zero", 0, "none")]
    number = float(value)
    if name.endswith("Req"):
        # A request count carried as a Real: none, and twice as many.
        return [("zero", 0.0, "no requests"), ("double", number * 2.0, "twice as many")]
    if name.endswith("Spe"):
        # A speed ratio lives in [0, 1]: halve it and run it flat out.
        return [("half", number * 0.5, "half nominal"), ("full", 1.0, "full speed")]
    if name.startswith("T"):
        return [("cold", number - 4.0, "4 K below nominal"), ("hot", number + 4.0, "4 K above")]
    if name.startswith("V"):
        return [("none", 0.0, "no flow"), ("double", number * 2.0, "twice nominal")]
    if name.startswith("dp"):
        return [("low", number * 0.5, "half nominal"), ("high", number * 1.5, "1.5× nominal")]
    if name.startswith("ppm"):
        return [("high", number * 1.5, "1.5× nominal")]
    if name.startswith("h"):
        return [("dry", number * 0.8, "0.8× nominal"), ("humid", number * 1.2, "1.2× nominal")]
    if name.startswith("u") and not name.startswith("u1"):
        return [("full", 1.0, "full signal")]
    if number == 0.0:
        return [("one", 1.0, "unit value")]
    return [("half", number * 0.5, "half nominal"), ("double", number * 2.0, "twice nominal")]


def absent_inputs(config_id: str) -> list[str]:
    """Interface inputs the engine's instance does not have for this parameter set
    (conditional ports), as recorded by the retained reference."""

    reference = reference_trace(config_id)
    return list(reference.get("absent_inputs", [])) if reference else []


def scenarios_for(
    config_id: str, *, limit: int | None = None, absent_inputs: list[str] | None = None
) -> list[Scenario]:
    """Nominal point, then one perturbation per input, in interface order."""

    translation = retained_translation(config_id)
    skip = set(
        absent_inputs if absent_inputs is not None else globals()["absent_inputs"](config_id)
    )
    inputs = [
        p
        for p in translation["points"]
        if p["source_interface_direction"] == "input" and p["name"] not in skip
    ]
    nominal = {p["name"]: _nominal_for(config_id, p["name"], _data_type(p)) for p in inputs}
    scenarios = [Scenario("nominal", dict(nominal), "the nominal operating point")]
    for point in inputs:
        name, data_type = point["name"], _data_type(point)
        for tag, value, why in _perturb(name, data_type, nominal[name]):
            scenarios.append(
                Scenario(f"{name} {tag}", {**nominal, name: value}, f"{name} at {why}")
            )
    return scenarios[:limit] if limit is not None else scenarios


def probe_cases(config_id: str) -> list[AcceptanceCase]:
    """Cases with no expectations of substance: what the retention script runs in OCE."""

    translation = retained_translation(config_id)
    outputs = [p for p in translation["points"] if p["source_interface_direction"] == "output"]
    numeric = next((p["name"] for p in outputs if _data_type(p) == "numeric"), None)
    expectation = (
        OutputExpectation(
            target=numeric, operator=ComparisonOperator.GREATER_THAN_OR_EQUAL, value=-1e300
        )
        if numeric
        else OutputExpectation(target=outputs[0]["name"], value=False)
    )
    return [
        AcceptanceCase(
            name=scenario.name,
            inputs=scenario.inputs,
            repeat=SCANS,
            step_seconds=SCAN_SECONDS,
            expectations=[expectation],
        )
        for scenario in scenarios_for(config_id)
    ]


# --- reference-derived expectations ---------------------------------------------------------

RELATIVE_TOLERANCE = 0.02
"""The D3 value band (docs/decisions/008): 2 % of the output's range over the suite."""


def _ranges(reference: dict[str, Any]) -> dict[str, float]:
    low: dict[str, float] = {}
    high: dict[str, float] = {}
    for case in reference["cases"]:
        for signal, values in case["outputs"].items():
            finite = [
                float(v)
                for v in values
                if isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(float(v))
            ]
            if not finite:
                continue
            low[signal] = min(low.get(signal, finite[0]), *finite)
            high[signal] = max(high.get(signal, finite[0]), *finite)
    return {signal: high[signal] - low[signal] for signal in low}


def expectations_for(config_id: str, case_name: str) -> list[OutputExpectation]:
    """The reference's final values, inside the D3 band."""

    reference = reference_trace(config_id)
    if reference is None:
        raise FileNotFoundError(
            f"no retained reference for {config_id}; run scripts/retain_tier2.py"
        )
    ranges = _ranges(reference)
    translation = retained_translation(config_id)
    types = {p["name"]: _data_type(p) for p in translation["points"]}
    entry = next(c for c in reference["cases"] if c["name"] == case_name)
    expectations: list[OutputExpectation] = []
    for signal, values in sorted(entry["outputs"].items()):
        final = values[-1]
        kind = types.get(signal, "numeric")
        if kind == "boolean" or isinstance(final, bool):
            expectations.append(OutputExpectation(target=signal, value=bool(final)))
            continue
        number = float(final)
        if not math.isfinite(number):
            continue  # an unbounded reference value cannot be graded by an interval
        tolerance = max(RELATIVE_TOLERANCE * ranges.get(signal, 0.0), 1e-6)
        if kind == "integer":
            tolerance = max(tolerance, 0.5)
        expectations.append(OutputExpectation(target=signal, value=number, tolerance=tolerance))
    return expectations


def cases_for(config_id: str) -> list[AcceptanceCase]:
    return [
        AcceptanceCase(
            name=scenario.name,
            inputs=scenario.inputs,
            repeat=SCANS,
            step_seconds=SCAN_SECONDS,
            expectations=expectations_for(config_id, scenario.name),
        )
        for scenario in scenarios_for(config_id)
    ]


def tier2_job(config_id: str) -> JobSpec:
    """A complete job for one configuration: LBNL's controller, mechanical scenarios,
    reference-derived expectations. Tier 2, labelled as such."""

    config = CONFIGURATIONS_BY_ID[config_id]
    points = points_for(config_id)
    graph = graph_for(config_id, points)
    return JobSpec(
        name=f"LBNL G36 {config.controller_id} ({config.variant})",
        site="Tier 2 library coverage",
        equipment_name=config.id.upper().replace("-", "_"),
        sequence=sequence_for(config_id),
        points=points,
        acceptance_tests=cases_for(config_id),
        control_graph=graph,
    )


__all__ = [
    "CONFIGURATIONS",
    "CONFIGURATIONS_BY_ID",
    "OPERATION_MODES",
    "absent_inputs",
    "SCANS",
    "SCAN_SECONDS",
    "Configuration",
    "Scenario",
    "cases_for",
    "coverage_report",
    "expectations_for",
    "graph_for",
    "nominal_input",
    "points_for",
    "probe_cases",
    "reference_trace",
    "retained_ids",
    "retained_translation",
    "scenarios_for",
    "sequence_for",
    "tier2_job",
]
