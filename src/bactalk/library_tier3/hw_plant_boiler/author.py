# ruff: noqa: E501 E701 E702
"""Author the hot water plant requirement set and write it as JSON (data).

The requirement set is data; this module is the reproducible way it was written.
``python -m bactalk.library_tier3.hw_plant_boiler.author`` rewrites requirements.json,
``--check`` verifies the committed file matches.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

G36 = "ASHRAE Guideline 36-2021"


def cite(section, paragraph=None, fidelity="paraphrase", note=None):
    d = {"document": G36, "section": section, "fidelity": fidelity}
    if paragraph:
        d["paragraph"] = paragraph
    if note:
        d["note"] = note
    return d


def c(point, op, value, deadband=0.0):
    d = {"point": point, "operator": op, "value": value}
    if deadband:
        d["deadband"] = deadband
    return d


def o(point, op, value, tolerance=0.0, upper=None):
    d = {"point": point, "operator": op, "value": value}
    if tolerance:
        d["tolerance"] = tolerance
    if upper is not None:
        d["upper"] = upper
    return d


def pt(
    name,
    label,
    dt,
    direction,
    unit=None,
    minimum=None,
    maximum=None,
    nominal=0.0,
    resolution=None,
    brick=None,
):
    d = {"name": name, "label": label, "data_type": dt, "direction": direction, "nominal": nominal}
    if unit:
        d["unit"] = unit
    if minimum is not None:
        d["minimum"] = minimum
    if maximum is not None:
        d["maximum"] = maximum
    if resolution:
        d["resolution"] = resolution
    if brick:
        d["brick_class"] = brick
    return d


T_LOCKOUT = 291.15
LOCKOUT_DB = 0.56
T_INI = 344.15
T_MIN = 327.15
T_MAX = 355.15
STAGE_DT = 2.8
T_LOW_ALARM = 322.15
V_DESIGN = 0.01
V_MIN = 0.003
DP_SET = 50000.0

points = [
    pt(
        "uSchOn",
        "Plant schedule occupied",
        "boolean",
        "input",
        nominal=True,
        brick="brick:Occupancy_Status",
    ),
    pt("nReqPla", "Hot water plant requests", "numeric", "input", "1", 0, 50, 2.0, 1.0),
    pt("nReqRes", "Supply temperature reset requests", "numeric", "input", "1", 0, 50, 0.0, 1.0),
    pt(
        "TOut",
        "Outdoor air temperature",
        "numeric",
        "input",
        "K",
        243.15,
        323.15,
        278.15,
        0.1,
        "brick:Outside_Air_Temperature_Sensor",
    ),
    pt(
        "TSup",
        "Hot water supply temperature",
        "numeric",
        "input",
        "K",
        273.15,
        373.15,
        344.15,
        0.1,
        "brick:Hot_Water_Supply_Temperature_Sensor",
    ),
    pt(
        "VHotWat_flow",
        "Hot water flow",
        "numeric",
        "input",
        "m3/s",
        0.0,
        0.02,
        0.005,
        0.0001,
        "brick:Hot_Water_Flow_Sensor",
    ),
    pt(
        "dpHotWat",
        "Hot water loop differential pressure",
        "numeric",
        "input",
        "Pa",
        0.0,
        200000.0,
        50000.0,
        100.0,
        "brick:Differential_Pressure_Sensor",
    ),
    pt("uBoi1Sta", "Boiler 1 proof", "boolean", "input", nominal=True, brick="brick:Run_Status"),
    pt("uBoi2Sta", "Boiler 2 proof", "boolean", "input", nominal=True, brick="brick:Run_Status"),
    pt("uPum1Sta", "Pump 1 proof", "boolean", "input", nominal=True, brick="brick:Run_Status"),
    pt("uPum2Sta", "Pump 2 proof", "boolean", "input", nominal=True, brick="brick:Run_Status"),
    pt(
        "yPla",
        "Plant enabled",
        "boolean",
        "output",
        nominal=False,
        brick="brick:Hot_Water_System_Enable_Command",
    ),
    pt(
        "yBoi1", "Boiler 1 enable", "boolean", "output", nominal=False, brick="brick:Boiler_Command"
    ),
    pt(
        "yBoi2", "Boiler 2 enable", "boolean", "output", nominal=False, brick="brick:Boiler_Command"
    ),
    pt(
        "TSupSet",
        "Hot water supply temperature setpoint",
        "numeric",
        "output",
        "K",
        T_MIN,
        T_MAX,
        T_INI,
        0.1,
        "brick:Supply_Hot_Water_Temperature_Setpoint",
    ),
    pt(
        "yPum1",
        "Pump 1 enable",
        "boolean",
        "output",
        nominal=False,
        brick="brick:Run_Enable_Command",
    ),
    pt(
        "yPum2",
        "Pump 2 enable",
        "boolean",
        "output",
        nominal=False,
        brick="brick:Run_Enable_Command",
    ),
    pt(
        "yPumSpe",
        "Pump speed",
        "numeric",
        "output",
        "1",
        0.0,
        1.0,
        0.0,
        0.01,
        "brick:Speed_Setpoint",
    ),
    pt(
        "yByp",
        "Minimum flow bypass valve position",
        "numeric",
        "output",
        "1",
        0.0,
        1.0,
        0.0,
        0.01,
        "brick:Valve_Command",
    ),
    pt(
        "yLowSupAla",
        "Low supply temperature alarm",
        "boolean",
        "output",
        nominal=False,
        brick="brick:Alarm",
    ),
    pt("yPumFaiAla", "Pump failure alarm", "boolean", "output", nominal=False, brick="brick:Alarm"),
    pt(
        "yBoiFaiAla",
        "Boiler failure alarm",
        "boolean",
        "output",
        nominal=False,
        brick="brick:Alarm",
    ),
]

reset_at_max = {
    "name": "reset settled at its maximum, supply at setpoint",
    "inputs": {"nReqRes": 10.0, "TSup": T_MAX},
    "seconds": 3000.0,
}
lag_staged = {"name": "lag boiler staged on", "inputs": {"TSup": 345.15}, "seconds": 720.0}

requirements = [
    {
        "id": "R-01",
        "title": "Plant enable",
        "kind": "enable",
        "text": "The hot water plant is enabled when the schedule is occupied, the outdoor air temperature is below the lockout temperature (291.15 K, 18 °C) and there is at least one hot water plant request. It is disabled when any of those stops holding for 3 minutes; the lockout has a 0.56 K (1 °F) deadband.",
        "citation": cite(
            "§5.21.2",
            "plant enable/disable",
            note="Section numbers are from the 2021 edition; the 3 min disable delay applies to every disable condition here (designer choice) and the lockout default is 18 °C.",
        ),
        "conditions": [
            c("uSchOn", "eq", True),
            c("TOut", "lt", T_LOCKOUT, LOCKOUT_DB),
            c("nReqPla", "gte", 1.0),
        ],
        "timing": {"release_seconds": 180.0},
        "outcomes": [o("yPla", "eq", True)],
        "otherwise": [o("yPla", "eq", False)],
        "parameters": {
            "TOutLockout_K": T_LOCKOUT,
            "lockoutDeadband_K": LOCKOUT_DB,
            "disableDelay_s": 180.0,
        },
    },
    {
        "id": "R-02",
        "title": "Lead boiler follows plant enable",
        "kind": "staging",
        "assumes": ["R-01"],
        "text": "With the plant enabled and the lead pump proven, the lead boiler (boiler 1) is enabled; it is disabled whenever the plant is disabled or no pump is proven.",
        "citation": cite("§5.21.3", "boiler staging"),
        "conditions": [c("uPum1Sta", "eq", True)],
        "outcomes": [o("yBoi1", "eq", True)],
        "otherwise": [o("yBoi1", "eq", False)],
    },
    {
        "id": "R-03",
        "title": "Stage up the lag boiler",
        "kind": "staging",
        "assumes": ["R-02"],
        "step_seconds": 30.0,
        "text": "With the lead boiler proven and the supply temperature reset settled at its maximum (355.15 K), the lag boiler is enabled when the supply temperature stays more than 2.8 K (5 °F) below the setpoint for 10 minutes. Once staged it stays on until the stage-down condition (R-04) is met.",
        "citation": cite(
            "§5.21.3",
            "stage up",
            note="The requirement is stated against the reset maximum so the threshold is a number; the logic compares with the live setpoint.",
        ),
        "setup": [reset_at_max],
        "conditions": [c("uBoi1Sta", "eq", True), c("TSup", "lt", round(T_MAX - STAGE_DT, 2))],
        "timing": {"delay_seconds": 600.0},
        "outcomes": [o("yBoi2", "eq", True)],
        "otherwise": [o("yBoi2", "eq", False)],
        "recovery": [o("yBoi2", "eq", True)],
        "parameters": {"stageUpDifferential_K": STAGE_DT, "stageUpDelay_s": 600.0},
    },
    {
        "id": "R-04",
        "title": "Stage down the lag boiler",
        "kind": "staging",
        "assumes": ["R-02"],
        "step_seconds": 30.0,
        "text": "With both boilers running and the reset settled at its maximum, the lag boiler is disabled when the supply temperature stays more than 2.8 K above the setpoint for 10 minutes; it stays enabled otherwise, and once staged off it stays off until the stage-up condition (R-03) is met again.",
        "citation": cite("§5.21.3", "stage down"),
        "setup": [reset_at_max, lag_staged],
        "conditions": [c("TSup", "gt", round(T_MAX + STAGE_DT, 2))],
        "timing": {"delay_seconds": 600.0},
        "outcomes": [o("yBoi2", "eq", False)],
        "otherwise": [o("yBoi2", "eq", True)],
        "recovery": [o("yBoi2", "eq", False)],
        "parameters": {"stageDownDifferential_K": STAGE_DT, "stageDownDelay_s": 600.0},
    },
    {
        "id": "R-05",
        "title": "Plant disable stops everything",
        "kind": "safety",
        "text": "When the schedule becomes unoccupied the plant is disabled after the 3 minute delay, and both boilers, both pumps and the pump speed command are off in the same scan.",
        "citation": cite("§5.21.2", "plant disable"),
        "conditions": [c("uSchOn", "eq", False)],
        "timing": {"delay_seconds": 180.0},
        "outcomes": [
            o("yPla", "eq", False),
            o("yBoi1", "eq", False),
            o("yBoi2", "eq", False),
            o("yPum1", "eq", False),
            o("yPum2", "eq", False),
            o("yPumSpe", "eq", 0.0),
        ],
        "otherwise": [o("yPla", "eq", True), o("yPum1", "eq", True)],
    },
    {
        "id": "R-06",
        "title": "Supply temperature reset trims without requests",
        "kind": "reset",
        "assumes": ["R-01"],
        "text": "The supply temperature setpoint is reset by trim and respond: initial 344.15 K, minimum 327.15 K, maximum 355.15 K, 10 minute delay after plant enable, 5 minute sample period, 0 ignored requests, trim −1.0 K, respond +1.0 K per request, maximum response +3.0 K. With no reset requests the setpoint has trimmed at least 0.5 K within 900 s of plant enable (the 600 s delay plus one 300 s sample period; the reset may land a scan or two later) and never goes below the minimum; with one request (the trim and one response cancel) it holds its value.",
        "citation": cite(
            "§5.21.4",
            "supply temperature reset",
            note="Trim and respond parameters are designer defaults in the style of §5.1.14.",
        ),
        "conditions": [c("nReqRes", "lte", 0.0)],
        "timing": {"delay_seconds": 900.0, "reference": "context", "tolerance_scans": 2},
        "outcomes": [o("TSupSet", "lte", T_INI - 0.5), o("TSupSet", "gte", T_MIN)],
        "otherwise": [o("TSupSet", "gte", T_INI)],
        "recovery": [o("TSupSet", "lte", T_INI - 0.5), o("TSupSet", "gte", T_MIN)],
        "parameters": {
            "TSupSetInitial_K": T_INI,
            "TSupSetMin_K": T_MIN,
            "TSupSetMax_K": T_MAX,
            "delay_s": 600.0,
            "period_s": 300.0,
            "trim_K": -1.0,
            "respond_K": 1.0,
            "maxResponse_K": 3.0,
        },
    },
    {
        "id": "R-07",
        "title": "Supply temperature reset responds to requests",
        "kind": "reset",
        "assumes": ["R-01"],
        "text": "With two or more reset requests the setpoint has risen at least 0.85 K above its initial value within 900 s of plant enable (the delay plus one sample period) and never exceeds the maximum; with one request (the trim and one response cancel) it stays where it is, so a raised setpoint holds when the requests drop to one.",
        "citation": cite("§5.21.4", "supply temperature reset"),
        "conditions": [c("nReqRes", "gte", 2.0)],
        "timing": {"delay_seconds": 900.0, "reference": "context", "tolerance_scans": 2},
        "outcomes": [o("TSupSet", "gte", T_INI + 0.85), o("TSupSet", "lte", T_MAX)],
        "otherwise": [o("TSupSet", "lte", T_INI, 0.01)],
        "recovery": [o("TSupSet", "gte", T_INI + 0.85), o("TSupSet", "lte", T_MAX)],
    },
    {
        "id": "R-08",
        "title": "Lead pump runs with the plant",
        "kind": "control",
        "assumes": ["R-01"],
        "text": "The lead hot water pump (pump 1 until a rotation) is commanded on whenever the plant is enabled and off when it is disabled.",
        "citation": cite("§5.21.5", "primary pumps"),
        "timing": {"release_seconds": 180.0},
        "outcomes": [o("yPum1", "eq", True)],
        "otherwise": [o("yPum1", "eq", False)],
    },
    {
        "id": "R-09",
        "title": "Lag pump stages on flow",
        "kind": "staging",
        "assumes": ["R-08"],
        "text": "With pump 1 leading, the lag pump (pump 2) is enabled when the hot water flow exceeds 60 % of design flow (0.006 m3/s) for 5 minutes and disabled when it falls below 40 % (0.004 m3/s) for 5 minutes.",
        "citation": cite(
            "§5.21.5",
            "pump staging",
            note="Flow ratios are designer defaults for a 0.01 m3/s design flow.",
        ),
        "conditions": [c("VHotWat_flow", "gt", 0.6 * V_DESIGN, 0.2 * V_DESIGN)],
        "timing": {"delay_seconds": 300.0, "release_seconds": 300.0},
        "outcomes": [o("yPum2", "eq", True)],
        "otherwise": [o("yPum2", "eq", False)],
        "parameters": {"VDesign_m3s": V_DESIGN, "stageUpRatio": 0.6, "stageDownRatio": 0.4},
    },
    {
        "id": "R-10",
        "title": "Pump speed rises when loop pressure is low",
        "kind": "loop",
        "assumes": ["R-08"],
        "text": "Pump speed is modulated to hold the loop differential pressure at its setpoint (50 kPa) between a minimum of 10 % and 100 %. With the pressure 20 kPa or more below setpoint for 5 minutes the speed is at least 95 %.",
        "citation": cite("§5.21.5", "pump speed control"),
        "conditions": [c("dpHotWat", "lt", DP_SET - 20000.0)],
        "timing": {"delay_seconds": 300.0},
        "outcomes": [o("yPumSpe", "gte", 0.95)],
        "otherwise": [o("yPumSpe", "gte", 0.1), o("yPumSpe", "lte", 1.0)],
        "parameters": {"dpSet_Pa": DP_SET, "speedMin": 0.1},
    },
    {
        "id": "R-11",
        "title": "Pump speed falls when loop pressure is high",
        "kind": "loop",
        "assumes": ["R-08"],
        "text": "With the loop differential pressure 20 kPa or more above setpoint for 5 minutes the pump speed is at its 10 % minimum (at most 15 %); it never drops below the minimum while a pump runs.",
        "citation": cite("§5.21.5", "pump speed control"),
        "conditions": [c("dpHotWat", "gt", DP_SET + 20000.0)],
        "timing": {"delay_seconds": 300.0},
        "outcomes": [o("yPumSpe", "lte", 0.15)],
        "otherwise": [o("yPumSpe", "gte", 0.1)],
    },
    {
        "id": "R-12",
        "title": "Minimum flow bypass opens on low flow",
        "kind": "loop",
        "assumes": ["R-08"],
        "text": "The minimum flow bypass valve is modulated to hold the boiler minimum flow (0.003 m3/s). With the flow at or below 0.001 m3/s for 5 minutes the valve is at least 90 % open.",
        "citation": cite("§5.21.6", "minimum flow bypass"),
        "conditions": [c("VHotWat_flow", "lt", 0.001)],
        "timing": {"delay_seconds": 300.0},
        "outcomes": [o("yByp", "gte", 0.9)],
        "otherwise": [o("yByp", "between", 0.0, upper=1.0)],
        "parameters": {"VMin_m3s": V_MIN},
    },
    {
        "id": "R-13",
        "title": "Minimum flow bypass closes on adequate flow",
        "kind": "loop",
        "assumes": ["R-08"],
        "text": "With the flow above 0.005 m3/s for 5 minutes the bypass valve is closed.",
        "citation": cite("§5.21.6", "minimum flow bypass"),
        "conditions": [c("VHotWat_flow", "gt", 0.005)],
        "timing": {"delay_seconds": 300.0},
        "outcomes": [o("yByp", "eq", 0.0, 0.001)],
        "otherwise": [o("yByp", "gte", 0.0)],
    },
    {
        "id": "R-14",
        "title": "Low supply temperature alarm",
        "kind": "alarm",
        "assumes": ["R-02"],
        "text": "With the lead boiler proven, a low supply temperature alarm is raised when the supply temperature stays below 322.15 K (49 °C) for 15 minutes and clears when it rises above 323.15 K (1 K deadband). A supply temperature reading below the sensor range also raises the alarm.",
        "citation": cite(
            "§5.21.8", "alarms", fidelity="designer", note="Limits and delay are designer defaults."
        ),
        "conditions": [c("uBoi1Sta", "eq", True), c("TSup", "lt", T_LOW_ALARM, 1.0)],
        "timing": {"delay_seconds": 900.0},
        "outcomes": [o("yLowSupAla", "eq", True)],
        "otherwise": [o("yLowSupAla", "eq", False)],
        "failures": [
            {
                "point": "TSup",
                "mode": "out_of_range_low",
                "outcomes": [o("yLowSupAla", "eq", True)],
                "note": "a supply temperature reading below the sensor range keeps the low supply alarm raised",
            }
        ],
        "parameters": {"TLowAlarm_K": T_LOW_ALARM, "alarmDelay_s": 900.0},
    },
    {
        "id": "R-15",
        "title": "Lead pump failure starts the standby pump",
        "kind": "alarm",
        "assumes": ["R-08"],
        "text": "When the commanded lead pump is not proven for 60 seconds a pump failure alarm is raised and the standby pump is commanded on; the alarm clears when the pump proves.",
        "citation": cite("§5.21.5", "pump failure"),
        "conditions": [c("uPum1Sta", "eq", False)],
        "timing": {"delay_seconds": 60.0},
        "outcomes": [o("yPumFaiAla", "eq", True), o("yPum2", "eq", True)],
        "otherwise": [o("yPumFaiAla", "eq", False)],
    },
    {
        "id": "R-16",
        "title": "Boiler failure alarm",
        "kind": "alarm",
        "assumes": ["R-02"],
        "text": "When a commanded boiler is not proven for 5 minutes a boiler failure alarm is raised; it clears when the boiler proves.",
        "citation": cite("§5.21.8", "alarms"),
        "conditions": [c("uBoi1Sta", "eq", False)],
        "timing": {"delay_seconds": 300.0},
        "outcomes": [o("yBoiFaiAla", "eq", True)],
        "otherwise": [o("yBoiFaiAla", "eq", False)],
    },
    {
        "id": "R-17",
        "title": "Lead/lag pump rotation on runtime",
        "kind": "rotation",
        "assumes": ["R-08"],
        "step_seconds": 300.0,
        "text": "The lead pump rotates to the other pump when its runtime since the last rotation or plant enable exceeds the other pump's by 24 hours (the runtime accumulators update one scan late, so the rotation may lag by up to two 300 s scans); the previous lead stops unless it is needed as lag.",
        "citation": cite(
            "§5.1.15",
            "lead/lag rotation",
            note="Runtime-based alternation; the 24 h differential is a designer default (daily balancing).",
        ),
        "timing": {"delay_seconds": 86400.0, "tolerance_scans": 2},
        "outcomes": [o("yPum2", "eq", True), o("yPum1", "eq", False)],
        "otherwise": [o("yPum1", "eq", False), o("yPum2", "eq", False)],
        "before": [o("yPum1", "eq", True), o("yPum2", "eq", False)],
        "parameters": {"rotationRuntime_s": 86400.0},
    },
    {
        "id": "R-18",
        "title": "Lag pump failure",
        "kind": "alarm",
        "assumes": ["R-08"],
        "text": "With the lag pump staged on flow, a pump failure alarm is raised when the lag pump is not proven for 60 seconds, and the alarm clears when it proves.",
        "citation": cite("§5.21.5", "pump failure"),
        "setup": [
            {
                "name": "lag pump staged on high flow",
                "inputs": {"VHotWat_flow": 0.008},
                "seconds": 400.0,
            }
        ],
        "conditions": [c("uPum2Sta", "eq", False)],
        "timing": {"delay_seconds": 60.0},
        "outcomes": [o("yPumFaiAla", "eq", True), o("yPum1", "eq", True)],
        "otherwise": [o("yPumFaiAla", "eq", False)],
    },
    {
        "id": "R-19",
        "title": "Lag boiler failure",
        "kind": "alarm",
        "assumes": ["R-02"],
        "step_seconds": 30.0,
        "text": "With the lag boiler staged, a boiler failure alarm is raised when the lag boiler is not proven for 5 minutes; it clears when the boiler proves.",
        "citation": cite("§5.21.8", "alarms"),
        "setup": [reset_at_max, lag_staged],
        "conditions": [c("uBoi2Sta", "eq", False)],
        "timing": {"delay_seconds": 300.0},
        "outcomes": [o("yBoiFaiAla", "eq", True)],
        "otherwise": [o("yBoiFaiAla", "eq", False)],
    },
    {
        "id": "R-20",
        "title": "Lead/lag pump rotation back",
        "kind": "rotation",
        "assumes": ["R-08"],
        "step_seconds": 300.0,
        "text": "Runtimes are reset at each rotation and at plant enable, so after a rotation the lead returns to pump 1 when pump 2 has run 24 hours more than pump 1 since then.",
        "citation": cite("§5.1.15", "lead/lag rotation", fidelity="designer"),
        "setup": [{"name": "first rotation to pump 2", "inputs": {}, "seconds": 90000.0}],
        "timing": {"delay_seconds": 86400.0, "tolerance_scans": 3},
        "outcomes": [o("yPum1", "eq", True), o("yPum2", "eq", False)],
        "otherwise": [o("yPum1", "eq", False), o("yPum2", "eq", False)],
        "before": [o("yPum2", "eq", True), o("yPum1", "eq", False)],
    },
]

invariants = [
    {
        "id": "I-01",
        "text": "The lag boiler never runs without the lead boiler",
        "citation": cite("§5.21.3"),
        "when": [c("yBoi2", "eq", True)],
        "then": [o("yBoi1", "eq", True)],
    },
    {
        "id": "I-02",
        "text": "A disabled plant commands nothing",
        "citation": cite("§5.21.2"),
        "when": [c("yPla", "eq", False)],
        "then": [
            o("yBoi1", "eq", False),
            o("yBoi2", "eq", False),
            o("yPum1", "eq", False),
            o("yPum2", "eq", False),
            o("yPumSpe", "eq", 0.0),
        ],
    },
    {
        "id": "I-03",
        "text": "The supply temperature setpoint stays inside its reset range",
        "citation": cite("§5.21.4"),
        "then": [o("TSupSet", "between", T_MIN, upper=T_MAX)],
    },
    {
        "id": "I-04",
        "text": "Pump speed and bypass position are fractions",
        "citation": cite("§5.21.5"),
        "then": [o("yPumSpe", "between", 0.0, upper=1.0), o("yByp", "between", 0.0, upper=1.0)],
    },
    {
        "id": "I-05",
        "text": "A boiler runs only with a pump commanded",
        "citation": cite("§5.21.3"),
        "when": [c("yBoi1", "eq", True)],
        "then": [o("yPla", "eq", True)],
    },
]

# Every timed requirement tolerates one scan: a per-second runtime (the Shadow Runtime,
# a Niagara station) sees a delay elapse up to one scan after a per-scan interpreter.
for requirement in requirements:
    timing = requirement.get("timing", {})
    if timing.get("delay_seconds") and not timing.get("tolerance_scans"):
        timing["tolerance_scans"] = 1

doc = {
    "schema": "bactalk.protocol-requirements/v1",
    "sequence_id": "hw-plant-boiler",
    "title": "Hot water plant: two boilers, two primary pumps, minimum flow bypass",
    "version": "1.0 (N9 draft, awaiting Gate G-ENG)",
    "tier": 3,
    "equipment_brick_class": "brick:Hot_Water_System",
    "sources": [
        {
            "document": G36,
            "edition": "2021, §5.21 hot water plant; §5.1.14 trim and respond; §5.1.15 lead/lag",
            "url": "https://www.ashrae.org/technical-resources/ashrae-standards-and-guidelines",
        }
    ],
    "step_seconds": 10.0,
    "points": points,
    "requirements": requirements,
    "invariants": invariants,
    "notes": "Drafted from the guideline text without an LBNL reference (Tier 3). Every citation is a paraphrase or a designer default and must be checked by the approving engineer; the questions listed in the test plan are the open items.",
}


def main(argv: list[str]) -> int:
    out = Path(__file__).with_name("requirements.json")
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        if out.read_text(encoding="utf-8") != text:
            print(f"{out} differs from the author; run without --check")
            return 1
        print(f"{out} matches")
        return 0
    out.write_text(text, encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
