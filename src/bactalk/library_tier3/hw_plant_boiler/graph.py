"""Logic author: the hot water plant in the typed IR, from the requirement set.

Every block group names the requirement it implements in ``graph.metadata``
("traceability"); the test plan and the coverage report read that back. This
module never imports the test author or the generated plan.
"""

from __future__ import annotations

from bactalk.domain import BlockKind, ControlGraph, DataType, PointSpec
from bactalk.protocol.authoring import GraphBuilder
from bactalk.protocol.requirements import RequirementSet

K = BlockKind


def build_graph(requirements: RequirementSet, points: list[PointSpec]) -> ControlGraph:
    parameters: dict[str, float] = {}
    for requirement in requirements.requirements:
        parameters.update(requirement.parameters)
    b = GraphBuilder()

    # --- boundary points -------------------------------------------------------------
    b.column(0)
    for point in points:
        if point.role in {"command", "alarm"}:
            continue
        kind = K.NUMERIC_INPUT if point.data_type == DataType.NUMERIC else K.BOOLEAN_INPUT
        b.add(point.name, kind, point.label, "boundary", default=point.default)

    # --- R-01 plant enable -----------------------------------------------------------
    b.column(1)
    lockout = parameters["TOutLockout_K"]
    deadband = parameters["lockoutDeadband_K"]
    b.add(
        "lockout_hys",
        K.HYSTERESIS,
        "Outdoor lockout (true above lockout + deadband)",
        "R-01",
        u_low=lockout,
        u_high=round(lockout + deadband, 4),
        initial=False,
    )
    b.link("TOut", "lockout_hys", "in")
    b.negate("below_lockout", "lockout_hys", "OAT below lockout", "R-01")
    b.const("one_request", 1.0, "One plant request", "R-01")
    b.gate(
        "requests_present",
        K.GREATER_THAN_OR_EQUAL,
        "nReqPla",
        "one_request",
        "Plant requests ≥ 1",
        "R-01",
    )
    b.gate("schedule_and_lockout", K.AND, "uSchOn", "below_lockout", "Schedule and lockout", "R-01")
    b.gate(
        "enable_raw", K.AND, "schedule_and_lockout", "requests_present", "Enable conditions", "R-01"
    )
    b.add(
        "plant_enable",
        K.BOOLEAN_DELAY,
        "Plant enable (3 min disable delay)",
        "R-01 R-05",
        on_delay_seconds=0.0,
        off_delay_seconds=parameters["disableDelay_s"],
    )
    b.link("enable_raw", "plant_enable", "in")
    b.add("yPla", K.BOOLEAN_OUTPUT, "Plant enabled", "R-01 R-05")
    b.link("plant_enable", "yPla", "in")

    # --- R-06/R-07 supply temperature reset --------------------------------------------
    b.column(2)
    b.add(
        "supply_reset",
        K.TRIM_AND_RESPOND,
        "Supply temperature trim and respond",
        "R-06 R-07",
        initial_setpoint=parameters["TSupSetInitial_K"],
        minimum_setpoint=parameters["TSupSetMin_K"],
        maximum_setpoint=parameters["TSupSetMax_K"],
        delay_seconds=parameters["delay_s"],
        sample_period_seconds=parameters["period_s"],
        ignored_requests=0,
        trim_amount=parameters["trim_K"],
        respond_amount=parameters["respond_K"],
        maximum_response=parameters["maxResponse_K"],
    )
    b.link("nReqRes", "supply_reset", "request_count")
    b.link("plant_enable", "supply_reset", "device_on")
    b.add("TSupSet", K.NUMERIC_OUTPUT, "Supply temperature setpoint", "R-06 R-07")
    b.link("supply_reset", "TSupSet", "in")

    # --- R-08/R-09/R-15/R-17 pumps --------------------------------------------------------
    b.column(3)
    # runtime accumulators read last scan's commands (no algebraic loop)
    b.add("pum1_ran", K.BOOLEAN_PRE_HOST_TICK, "Pump 1 ran last scan", "R-17")
    b.add("pum2_ran", K.BOOLEAN_PRE_HOST_TICK, "Pump 2 ran last scan", "R-17")
    b.add("lead_was_2", K.BOOLEAN_PRE_HOST_TICK, "Pump 2 led last scan", "R-20")
    b.add("lead_rose", K.ONE_SHOT, "Lead changed to pump 2", "R-20")
    b.add("lead_fell", K.BOOLEAN_FALLING_EDGE, "Lead changed to pump 1", "R-20")
    b.link("lead_was_2", "lead_rose", "in")
    b.link("lead_was_2", "lead_fell", "in")
    b.gate("lead_changed", K.OR, "lead_rose", "lead_fell", "Lead changed", "R-20")
    # one scan after enable (a pre block), so the pulse lands on a recorded scan
    b.add("plant_was_on", K.BOOLEAN_PRE_HOST_TICK, "Plant enabled last scan", "R-17 R-20")
    b.link("plant_enable", "plant_was_on", "in")
    b.add("plant_started", K.ONE_SHOT, "Plant just enabled", "R-17 R-20")
    b.link("plant_was_on", "plant_started", "in")
    b.gate(
        "rotation_reset",
        K.OR,
        "lead_changed",
        "plant_started",
        "Runtimes reset at rotation or plant enable",
        "R-17 R-20",
    )
    for pump in ("1", "2"):
        b.add(
            f"pum{pump}_runtime",
            K.TIMER_ACCUMULATING,
            f"Pump {pump} runtime since rotation",
            "R-17 R-20",
            threshold_seconds=0.0,
        )
        b.link(f"pum{pump}_ran", f"pum{pump}_runtime", "in")
        b.link("rotation_reset", f"pum{pump}_runtime", "reset")
    b.gate_slots(
        "runtime_1_minus_2",
        K.SUBTRACT,
        ("pum1_runtime", "elapsed"),
        ("pum2_runtime", "elapsed"),
        "Runtime pump 1 − pump 2",
        "R-17",
    )
    b.gate_slots(
        "runtime_2_minus_1",
        K.SUBTRACT,
        ("pum2_runtime", "elapsed"),
        ("pum1_runtime", "elapsed"),
        "Runtime pump 2 − pump 1",
        "R-17",
    )
    b.const(
        "rotation_runtime", parameters["rotationRuntime_s"], "Rotation runtime differential", "R-17"
    )
    b.gate(
        "rotate_to_2",
        K.GREATER_THAN_OR_EQUAL,
        "runtime_1_minus_2",
        "rotation_runtime",
        "Pump 1 ran 100 h more",
        "R-17",
    )
    b.gate(
        "rotate_to_1",
        K.GREATER_THAN_OR_EQUAL,
        "runtime_2_minus_1",
        "rotation_runtime",
        "Pump 2 ran 100 h more",
        "R-17",
    )
    b.add("lead_is_2", K.BOOLEAN_SET_RESET, "Pump 2 leads", "R-17")
    b.link("rotate_to_2", "lead_is_2", "set")
    b.link("rotate_to_1", "lead_is_2", "clear")
    b.link("lead_is_2", "lead_was_2", "in")
    b.negate("lead_is_1", "lead_is_2", "Pump 1 leads", "R-17")

    b.column(4)
    b.add(
        "flow_hys",
        K.HYSTERESIS,
        "Flow above lag stage-up ratio",
        "R-09",
        u_low=parameters["stageDownRatio"] * parameters["VDesign_m3s"],
        u_high=parameters["stageUpRatio"] * parameters["VDesign_m3s"],
        initial=False,
    )
    b.link("VHotWat_flow", "flow_hys", "in")
    b.add(
        "lag_pump_request",
        K.BOOLEAN_DELAY,
        "Lag pump request (5 min on/off)",
        "R-09",
        on_delay_seconds=300.0,
        off_delay_seconds=300.0,
    )
    b.link("flow_hys", "lag_pump_request", "in")
    # failure: commanded and not proven for 60 s (the failed pump stays commanded so the
    # alarm holds; the standby starts)
    b.add("pum1_cmd_pre", K.BOOLEAN_PRE_HOST_TICK, "Pump 1 commanded last scan", "R-15")
    b.add("pum2_cmd_pre", K.BOOLEAN_PRE_HOST_TICK, "Pump 2 commanded last scan", "R-15")
    b.negate("pum1_not_proven", "uPum1Sta", "Pump 1 not proven", "R-15")
    b.negate("pum2_not_proven", "uPum2Sta", "Pump 2 not proven", "R-18")
    b.gate(
        "pum1_missing",
        K.AND,
        "pum1_cmd_pre",
        "pum1_not_proven",
        "Pump 1 commanded, not proven",
        "R-15",
    )
    b.gate(
        "pum2_missing",
        K.AND,
        "pum2_cmd_pre",
        "pum2_not_proven",
        "Pump 2 commanded, not proven",
        "R-18",
    )
    b.timer("pum1_fail_timer", "pum1_missing", 60.0, "Pump 1 failure (60 s)", "R-15")
    b.timer("pum2_fail_timer", "pum2_missing", 60.0, "Pump 2 failure (60 s)", "R-18")
    b.gate_slots(
        "pump_failure",
        K.OR,
        ("pum1_fail_timer", "passed"),
        ("pum2_fail_timer", "passed"),
        "Any pump failed",
        "R-15",
    )
    b.add("yPumFaiAla", K.BOOLEAN_OUTPUT, "Pump failure alarm", "R-15")
    b.link("pump_failure", "yPumFaiAla", "in")

    b.column(5)
    # pump 1 runs when it leads, when lag is requested, or when pump 2 has failed
    b.gate(
        "pum1_lag_or_lead",
        K.OR,
        "lead_is_1",
        "lag_pump_request",
        "Pump 1 lead or lag",
        "R-08 R-09 R-17",
    )
    b.gate_slots(
        "pum1_wanted",
        K.OR,
        ("pum1_lag_or_lead", "out"),
        ("pum2_fail_timer", "passed"),
        "Pump 1 wanted",
        "R-08 R-15",
    )
    b.gate("pum1_cmd", K.AND, "plant_enable", "pum1_wanted", "Pump 1 command", "R-05 R-08")
    b.gate(
        "pum2_lag_or_lead", K.OR, "lead_is_2", "lag_pump_request", "Pump 2 lead or lag", "R-09 R-17"
    )
    b.gate_slots(
        "pum2_wanted",
        K.OR,
        ("pum2_lag_or_lead", "out"),
        ("pum1_fail_timer", "passed"),
        "Pump 2 wanted",
        "R-09 R-15",
    )
    b.gate("pum2_cmd", K.AND, "plant_enable", "pum2_wanted", "Pump 2 command", "R-05 R-09")
    b.add("yPum1", K.BOOLEAN_OUTPUT, "Pump 1 enable", "R-08")
    b.add("yPum2", K.BOOLEAN_OUTPUT, "Pump 2 enable", "R-09")
    b.link("pum1_cmd", "yPum1", "in")
    b.link("pum2_cmd", "yPum2", "in")
    b.link("pum1_cmd", "pum1_ran", "in")
    b.link("pum2_cmd", "pum2_ran", "in")
    b.link("pum1_cmd", "pum1_cmd_pre", "in")
    b.link("pum2_cmd", "pum2_cmd_pre", "in")

    # --- R-10/R-11 pump speed ------------------------------------------------------------
    b.column(6)
    b.gate("any_pump", K.OR, "pum1_cmd", "pum2_cmd", "Any pump commanded", "R-10 R-11")
    b.const("dp_setpoint", parameters["dpSet_Pa"], "Loop differential pressure setpoint", "R-10")
    b.bconst("no_reset", False, "Loops never reset", "R-10 R-12")
    b.add(
        "speed_loop",
        K.PID_WITH_RESET,
        "Pump speed loop (P, reverse acting)",
        "R-10 R-11",
        controller_type="P",
        k=1.0 / 20000.0,
        r=1.0,
        y_min=parameters["speedMin"],
        y_max=1.0,
        reverse_acting=True,
    )
    b.link("dp_setpoint", "speed_loop", "setpoint")
    b.link("dpHotWat", "speed_loop", "measurement")
    b.link("no_reset", "speed_loop", "trigger")
    b.const("zero_speed", 0.0, "Zero speed", "R-05")
    b.add("speed_select", K.NUMERIC_SWITCH, "Speed when a pump runs, else 0", "R-05 R-10")
    b.link("any_pump", "speed_select", "selector")
    b.link("speed_loop", "speed_select", "when_true")
    b.link("zero_speed", "speed_select", "when_false")
    b.add("yPumSpe", K.NUMERIC_OUTPUT, "Pump speed", "R-10 R-11")
    b.link("speed_select", "yPumSpe", "in")

    # --- R-12/R-13 minimum flow bypass ---------------------------------------------------
    b.const("min_flow", parameters["VMin_m3s"], "Boiler minimum flow", "R-12")
    b.add(
        "bypass_loop",
        K.PID_WITH_RESET,
        "Minimum flow bypass loop (P, reverse acting)",
        "R-12 R-13",
        controller_type="P",
        k=500.0,
        r=1.0,
        y_min=0.0,
        y_max=1.0,
        reverse_acting=True,
    )
    b.link("min_flow", "bypass_loop", "setpoint")
    b.link("VHotWat_flow", "bypass_loop", "measurement")
    b.link("no_reset", "bypass_loop", "trigger")
    b.const("bypass_closed", 0.0, "Bypass closed", "R-12")
    b.add("bypass_select", K.NUMERIC_SWITCH, "Bypass when the plant runs, else closed", "R-12")
    b.link("plant_enable", "bypass_select", "selector")
    b.link("bypass_loop", "bypass_select", "when_true")
    b.link("bypass_closed", "bypass_select", "when_false")
    b.add("yByp", K.NUMERIC_OUTPUT, "Bypass valve position", "R-12 R-13")
    b.link("bypass_select", "yByp", "in")

    # --- R-02/R-03/R-04 boilers ------------------------------------------------------------
    b.column(7)
    b.gate("pum1_proven", K.AND, "pum1_cmd", "uPum1Sta", "Pump 1 proven", "R-02")
    b.gate("pum2_proven", K.AND, "pum2_cmd", "uPum2Sta", "Pump 2 proven", "R-02")
    b.gate("pump_proven", K.OR, "pum1_proven", "pum2_proven", "A pump is proven", "R-02")
    b.gate("boi1_cmd", K.AND, "plant_enable", "pump_proven", "Lead boiler command", "R-02 R-05")
    b.add("yBoi1", K.BOOLEAN_OUTPUT, "Boiler 1 enable", "R-02")
    b.link("boi1_cmd", "yBoi1", "in")
    b.const("stage_dt", parameters["stageUpDifferential_K"], "Staging differential", "R-03 R-04")
    b.gate("stage_up_limit", K.SUBTRACT, "TSupSet", "stage_dt", "Setpoint − differential", "R-03")
    b.gate("stage_down_limit", K.ADD, "TSupSet", "stage_dt", "Setpoint + differential", "R-04")
    b.gate(
        "supply_low", K.LESS_THAN, "TSup", "stage_up_limit", "Supply below setpoint − dT", "R-03"
    )
    b.gate(
        "supply_high",
        K.GREATER_THAN,
        "TSup",
        "stage_down_limit",
        "Supply above setpoint + dT",
        "R-04",
    )
    b.gate("lead_proven", K.AND, "boi1_cmd", "uBoi1Sta", "Lead boiler proven", "R-03")
    b.gate("stage_up_cond", K.AND, "lead_proven", "supply_low", "Stage-up condition", "R-03")
    b.timer(
        "stage_up_timer", "stage_up_cond", parameters["stageUpDelay_s"], "Stage-up delay", "R-03"
    )
    b.timer(
        "stage_down_timer",
        "supply_high",
        parameters["stageDownDelay_s"],
        "Stage-down delay",
        "R-04",
    )
    b.negate("plant_off", "plant_enable", "Plant disabled", "R-05")
    b.gate_slots(
        "stage_down_or_off",
        K.OR,
        ("stage_down_timer", "passed"),
        ("plant_off", "out"),
        "Stage down or plant off",
        "R-04 R-05",
    )
    b.add("lag_boiler_latch", K.BOOLEAN_SET_RESET, "Lag boiler staged", "R-03 R-04")
    b.link("stage_up_timer", "lag_boiler_latch", "set", "passed")
    b.link("stage_down_or_off", "lag_boiler_latch", "clear")
    b.gate("boi2_cmd", K.AND, "lag_boiler_latch", "boi1_cmd", "Lag boiler command", "R-03 R-04")
    b.add("yBoi2", K.BOOLEAN_OUTPUT, "Boiler 2 enable", "R-03 R-04")
    b.link("boi2_cmd", "yBoi2", "in")

    # --- R-14/R-16 alarms -------------------------------------------------------------------
    b.column(8)
    low = parameters["TLowAlarm_K"]
    b.add(
        "low_supply_hys",
        K.HYSTERESIS,
        "Supply above low-alarm limit (+1 K)",
        "R-14",
        u_low=low,
        u_high=round(low + 1.0, 4),
        initial=True,
    )
    b.link("TSup", "low_supply_hys", "in")
    b.negate("supply_too_low", "low_supply_hys", "Supply below low-alarm limit", "R-14")
    b.gate("low_alarm_cond", K.AND, "lead_proven", "supply_too_low", "Low supply condition", "R-14")
    b.timer(
        "low_alarm_timer", "low_alarm_cond", parameters["alarmDelay_s"], "Low supply delay", "R-14"
    )
    b.add("yLowSupAla", K.BOOLEAN_OUTPUT, "Low supply temperature alarm", "R-14")
    b.link("low_alarm_timer", "yLowSupAla", "in", "passed")
    b.negate("boi1_not_proven", "uBoi1Sta", "Boiler 1 not proven", "R-16")
    b.negate("boi2_not_proven", "uBoi2Sta", "Boiler 2 not proven", "R-19")
    b.gate(
        "boi1_missing",
        K.AND,
        "boi1_cmd",
        "boi1_not_proven",
        "Boiler 1 commanded, not proven",
        "R-16",
    )
    b.gate(
        "boi2_missing",
        K.AND,
        "boi2_cmd",
        "boi2_not_proven",
        "Boiler 2 commanded, not proven",
        "R-16",
    )
    b.timer("boi1_fail_timer", "boi1_missing", 300.0, "Boiler 1 failure (5 min)", "R-16")
    b.timer("boi2_fail_timer", "boi2_missing", 300.0, "Boiler 2 failure (5 min)", "R-19")
    b.gate_slots(
        "boiler_failure",
        K.OR,
        ("boi1_fail_timer", "passed"),
        ("boi2_fail_timer", "passed"),
        "Any boiler failed",
        "R-16",
    )
    b.add("yBoiFaiAla", K.BOOLEAN_OUTPUT, "Boiler failure alarm", "R-16")
    b.link("boiler_failure", "yBoiFaiAla", "in")

    return ControlGraph(
        name="HotWaterPlant",
        blocks=b.blocks,
        links=b.links,
        metadata={
            "sequence_id": requirements.sequence_id,
            "requirements_digest": requirements.digest(),
            "traceability": {key: sorted(set(value)) for key, value in b.trace.items()},
            "source": "docs/library-authoring.md (Tier 3, logic author)",
        },
    )


__all__ = ["build_graph"]
