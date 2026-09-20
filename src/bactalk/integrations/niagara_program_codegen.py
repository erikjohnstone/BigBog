from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from pathlib import PurePosixPath
from typing import Any

from bactalk.domain import Block, BlockKind, ControlGraph, canonical_json


class NiagaraProgramCodegenError(ValueError):
    pass


def _java_number(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise NiagaraProgramCodegenError("Java controller constants must be finite")
    return repr(number)


def _java_string(value: str) -> str:
    """Return a deterministic Java/JSON-compatible string literal."""

    return json.dumps(value, ensure_ascii=True)


def _pid_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.PID_WITH_RESET:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    return {
        "controller_type": str(block.config.get("controller_type", "PI")),
        "k": float(block.config.get("k", 1.0)),
        "ti": float(block.config.get("ti", 0.5)),
        "td": float(block.config.get("td", 0.1)),
        "r": float(block.config.get("r", 1.0)),
        "ni": float(block.config.get("ni", 0.9)),
        "nd": float(block.config.get("nd", 10.0)),
        "y_min": float(block.config.get("y_min", 0.0)),
        "y_max": float(block.config.get("y_max", 1.0)),
        "xi_start": float(block.config.get("xi_start", 0.0)),
        "yd_start": float(block.config.get("yd_start", 0.0)),
        "y_reset": float(block.config.get("y_reset", block.config.get("xi_start", 0.0))),
        "reverse_acting": bool(block.config.get("reverse_acting", True)),
    }


def _pid_kernel_members(config: dict[str, Any]) -> str:
    controller_type = config["controller_type"]
    with_integral = controller_type in {"PI", "PID"}
    with_derivative = controller_type in {"PD", "PID"}
    constants = {
        "K": config["k"],
        "TI": config["ti"],
        "TD": config["td"],
        "R": config["r"],
        "NI": config["ni"],
        "ND": config["nd"],
        "Y_MIN": config["y_min"],
        "Y_MAX": config["y_max"],
        "XI_START": config["xi_start"],
        "YD_START": config["yd_start"],
        "Y_RESET": config["y_reset"],
    }
    numeric_constants = "\n".join(
        f"  private static final double {name} = {_java_number(value)};"
        for name, value in constants.items()
    )
    return f"""  private static final boolean WITH_INTEGRAL = {str(with_integral).lower()};
  private static final boolean WITH_DERIVATIVE = {str(with_derivative).lower()};
  private static final boolean REVERSE_ACTING = {str(config["reverse_acting"]).lower()};
{numeric_constants}

  private double integral = XI_START;
  private double derivativeState = 0.0;
  private boolean previousTrigger = false;
  private double previousTimeSeconds = Double.NaN;

  private void resetControllerState() {{
    integral = XI_START;
    derivativeState = 0.0;
    previousTrigger = false;
    previousTimeSeconds = Double.NaN;
  }}

  public double step(double timeSeconds, double setpoint, double measurement, boolean trigger) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)
        || Double.isNaN(setpoint) || Double.isInfinite(setpoint)
        || Double.isNaN(measurement) || Double.isInfinite(measurement)) {{
      throw new IllegalArgumentException("PIDWithReset inputs must be finite");
    }}
    boolean firstTick = Double.isNaN(previousTimeSeconds);
    if (!firstTick && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("PIDWithReset time must be monotonic");
    }}
    double dt = firstTick ? 0.0 : timeSeconds - previousTimeSeconds;
    double reverseSign = REVERSE_ACTING ? 1.0 : -1.0;
    double error = reverseSign * (setpoint - measurement) / R;
    double proportional = K * error;
    double derivativeGain = K * TD;
    double derivativeTime = TD / ND;
    double derivative = WITH_DERIVATIVE
        ? (firstTick ? YD_START
            : (derivativeGain / derivativeTime) * (error - derivativeState))
        : 0.0;
    double integralOutput = WITH_INTEGRAL ? integral : 0.0;
    double proportionalDerivative = proportional + derivative;
    double unlimited = proportionalDerivative + integralOutput;
    double output = unlimited > Y_MAX ? Y_MAX : (unlimited < Y_MIN ? Y_MIN : unlimited);

    if (WITH_INTEGRAL) {{
      boolean risingReset = trigger && !previousTrigger;
      if (risingReset) {{
        integral = Y_RESET - proportionalDerivative;
      }} else {{
        double antiWindup = (unlimited - output) / (K * NI);
        double correctedError = error - antiWindup;
        integral = integralOutput + (K / TI) * correctedError * dt;
      }}
      previousTrigger = trigger;
    }}
    if (WITH_DERIVATIVE) {{
      double initialDerivativeState = firstTick
          ? (Math.abs(derivativeGain) < 1.0e-15
              ? error
              : error - derivativeTime * YD_START / derivativeGain)
          : derivativeState;
      double ratio = dt / derivativeTime;
      derivativeState = (initialDerivativeState + ratio * error) / (1.0 + ratio);
    }}
    previousTimeSeconds = timeSeconds;
    return output;
  }}
"""


def _pid_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Reals.PIDWithReset qualification kernel.
public final class {class_name} {{
{_pid_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 4 != 0) {{
      throw new IllegalArgumentException("expected groups: time setpoint measurement trigger");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 4) {{
      double time = Double.parseDouble(args[index]);
      double setpoint = Double.parseDouble(args[index + 1]);
      double measurement = Double.parseDouble(args[index + 2]);
      boolean trigger = Double.parseDouble(args[index + 3]) != 0.0;
      System.out.println(Double.toString(controller.step(time, setpoint, measurement, trigger)));
    }}
  }}
}}
"""


def _pid_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _pid_kernel_members(config).replace("  private static final", "private static final")
    members = members.replace("  private double", "private double")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public double", "public double")
    return f"""// Generated by BACTalk from the pinned CDL/OCE PIDWithReset contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};

{members}
public void onStart() throws Exception {{
  resetControllerState();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getSetpoint().getStatus().isOk()
        || !getMeasurement().getStatus().isOk()
        || !getTrigger().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = System.currentTimeMillis() / 1000.0;
    double result = step(
        timeSeconds,
        getSetpoint().getValue(),
        getMeasurement().getValue(),
        getTrigger().getValue());
    getOut().setValue(result);
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{
    ticket.cancel();
    ticket = null;
  }}
}}

private void scheduleNext() {{
  if (ticket != null) {{
    ticket.cancel();
  }}
  ticket = Clock.schedule(
      getComponent(),
      BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS),
      BProgram.execute,
      null);
}}
"""


def _trim_and_respond_config(block: Block) -> dict[str, Any]:
    if block.kind not in {
        BlockKind.TRIM_AND_RESPOND,
        BlockKind.TRIM_AND_RESPOND_HOLD,
    }:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    hold_enabled = block.kind == BlockKind.TRIM_AND_RESPOND_HOLD
    if block.config.get("hold_enabled", False) is not hold_enabled:
        raise NiagaraProgramCodegenError(
            "TrimAndRespond typed block kind and hold_enabled contract disagree"
        )
    config = {
        "initial_setpoint": float(block.config["initial_setpoint"]),
        "minimum_setpoint": float(block.config["minimum_setpoint"]),
        "maximum_setpoint": float(block.config["maximum_setpoint"]),
        "delay_seconds": float(block.config["delay_seconds"]),
        "sample_period_seconds": float(block.config["sample_period_seconds"]),
        "ignored_requests": float(block.config["ignored_requests"]),
        "trim_amount": float(block.config["trim_amount"]),
        "respond_amount": float(block.config["respond_amount"]),
        "maximum_response": float(block.config["maximum_response"]),
        "hold_enabled": hold_enabled,
    }
    if hold_enabled:
        config["hold_duration_seconds"] = float(block.config["hold_duration_seconds"])
    return config


def _trim_and_respond_kernel_members(config: dict[str, Any]) -> str:
    constants = {
        "INITIAL_SETPOINT": config["initial_setpoint"],
        "MINIMUM_SETPOINT": config["minimum_setpoint"],
        "MAXIMUM_SETPOINT": config["maximum_setpoint"],
        "DELAY_SECONDS": config["delay_seconds"],
        "SAMPLE_PERIOD_SECONDS": config["sample_period_seconds"],
        "IGNORED_REQUESTS": config["ignored_requests"],
        "TRIM_AMOUNT": config["trim_amount"],
        "RESPOND_AMOUNT": config["respond_amount"],
        "MAXIMUM_RESPONSE": config["maximum_response"],
    }
    numeric_constants = "\n".join(
        f"  private static final double {name} = {_java_number(value)};"
        for name, value in constants.items()
    )
    hold_enabled = bool(config["hold_enabled"])
    hold_constant = (
        "\n  private static final double HOLD_DURATION_SECONDS = "
        f"{_java_number(config['hold_duration_seconds'])};"
        if hold_enabled
        else ""
    )
    hold_members = (
        """
  private boolean holdInitialized = false;
  private boolean holdOut = false;
  private double holdElapsed = 0.0;
  private boolean holdLatch = false;
  private long sampleTriggerLastIndex = -1L;"""
        if hold_enabled
        else ""
    )
    hold_reset = (
        """
    holdInitialized = false;
    holdOut = false;
    holdElapsed = 0.0;
    holdLatch = false;
    sampleTriggerLastIndex = -1L;"""
        if hold_enabled
        else ""
    )
    hold_parameter = ", boolean hold" if hold_enabled else ""
    hold_logic = (
        """
    if (!holdInitialized) {
      holdInitialized = true;
      holdOut = hold;
      holdElapsed = 0.0;
    } else {
      holdElapsed += dt;
      if (hold != holdOut) {
        double requiredHold = holdOut ? HOLD_DURATION_SECONDS : 0.0;
        if (holdElapsed >= requiredHold) {
          holdOut = hold;
          holdElapsed = 0.0;
        }
      }
    }
    long triggerIndex = (long) Math.floor(
        timeSeconds / SAMPLE_PERIOD_SECONDS + 1.0e-9);
    if (triggerIndex > sampleTriggerLastIndex) {
      sampleTriggerLastIndex = triggerIndex;
      // Exact CDL Latch result at each clock: clear-dominant, so y = holdOut.
      holdLatch = holdOut;
    }
    holdReset = holdLatch;
"""
        if hold_enabled
        else ""
    )
    return f"""{numeric_constants}
{hold_constant}

  private boolean delayOut = false;
  private boolean delayPending = false;
  private double delayElapsed = 0.0;
  private boolean samplerInitialized = false;
  private double samplerHeld = 0.0;
  private double samplerT0 = 0.0;
  private long samplerLastIndex = -1L;
  private boolean unitInitialized = false;
  private double unitHeld = INITIAL_SETPOINT;
  private double unitStaged = INITIAL_SETPOINT;
  private double unitT0 = 0.0;
  private long unitLastIndex = -1L;
  private double previousTimeSeconds = Double.NaN;
{hold_members}

  private void resetControllerState() {{
    delayOut = false;
    delayPending = false;
    delayElapsed = 0.0;
    samplerInitialized = false;
    samplerHeld = 0.0;
    samplerT0 = 0.0;
    samplerLastIndex = -1L;
    unitInitialized = false;
    unitHeld = INITIAL_SETPOINT;
    unitStaged = INITIAL_SETPOINT;
    unitT0 = 0.0;
    unitLastIndex = -1L;
    previousTimeSeconds = Double.NaN;
{hold_reset}
  }}

  public double step(double timeSeconds, double requestCount, boolean deviceOn{hold_parameter}) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)
        || Double.isNaN(requestCount) || Double.isInfinite(requestCount)) {{
      throw new IllegalArgumentException("TrimAndRespond inputs must be finite");
    }}
    boolean firstTick = Double.isNaN(previousTimeSeconds);
    if (!firstTick && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("TrimAndRespond time must be monotonic");
    }}
    double dt = firstTick ? 0.0 : timeSeconds - previousTimeSeconds;
    double trueDelay = DELAY_SECONDS + SAMPLE_PERIOD_SECONDS;
    boolean holdReset = false;
{hold_logic}

    if (deviceOn == delayOut) {{
      delayElapsed = 0.0;
      delayPending = deviceOn;
    }} else if (deviceOn != delayPending) {{
      delayPending = deviceOn;
      delayElapsed = 0.0;
      if (!deviceOn || trueDelay <= 0.0) {{
        delayOut = deviceOn;
      }}
    }} else {{
      delayElapsed += dt;
      double activeDelay = deviceOn ? trueDelay : 0.0;
      if (delayElapsed >= activeDelay) {{
        delayOut = deviceOn;
        delayElapsed = 0.0;
      }}
    }}

    if (!samplerInitialized) {{
      samplerT0 = Math.floor(timeSeconds / SAMPLE_PERIOD_SECONDS)
          * SAMPLE_PERIOD_SECONDS;
      samplerLastIndex = (long) Math.floor(
          (timeSeconds - samplerT0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      samplerInitialized = true;
      samplerHeld = requestCount;
    }} else {{
      long sampleIndex = (long) Math.floor(
          (timeSeconds - samplerT0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      if (sampleIndex > samplerLastIndex) {{
        samplerLastIndex = sampleIndex;
        samplerHeld = requestCount;
      }}
    }}

    boolean unitDue = false;
    double unitOutput;
    if (!unitInitialized) {{
      unitOutput = INITIAL_SETPOINT;
    }} else {{
      long unitIndex = (long) Math.floor(
          (timeSeconds - unitT0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      unitDue = unitIndex > unitLastIndex;
      unitOutput = unitDue ? unitStaged : unitHeld;
    }}

    double requestDelta = samplerHeld - IGNORED_REQUESTS;
    double response = Math.copySign(
        Math.min(Math.abs(RESPOND_AMOUNT) * requestDelta, Math.abs(MAXIMUM_RESPONSE)),
        RESPOND_AMOUNT);
    double netReset;
    if (holdReset) {{
      netReset = 0.0;
    }} else if (!delayOut) {{
      netReset = 0.0;
    }} else if (requestDelta > 0.0) {{
      netReset = TRIM_AMOUNT + response;
    }} else {{
      netReset = TRIM_AMOUNT;
    }}
    double candidate = Math.max(
        MINIMUM_SETPOINT,
        Math.min(MAXIMUM_SETPOINT, unitOutput + netReset));
    double output = deviceOn ? candidate : INITIAL_SETPOINT;

    if (!unitInitialized) {{
      unitT0 = Math.floor(timeSeconds / SAMPLE_PERIOD_SECONDS)
          * SAMPLE_PERIOD_SECONDS;
      unitInitialized = true;
      unitLastIndex = (long) Math.floor(
          (timeSeconds - unitT0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      unitStaged = output;
    }} else if (unitDue) {{
      unitLastIndex = (long) Math.floor(
          (timeSeconds - unitT0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      unitHeld = unitStaged;
      unitStaged = output;
    }}
    previousTimeSeconds = timeSeconds;
    return output;
  }}
"""


def _trim_and_respond_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    hold_enabled = bool(config["hold_enabled"])
    variant = "have_hol=true" if hold_enabled else "have_hol=false"
    width = 4 if hold_enabled else 3
    expected = (
        "time requestCount deviceOn hold"
        if hold_enabled
        else "time requestCount deviceOn"
    )
    hold_parse = (
        "\n      boolean hold = Double.parseDouble(args[index + 3]) != 0.0;"
        if hold_enabled
        else ""
    )
    call_suffix = ", hold" if hold_enabled else ""
    return f"""// Generated by BACTalk. Exact G36 TrimAndRespond {variant} kernel.
public final class {class_name} {{
{_trim_and_respond_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % {width} != 0) {{
      throw new IllegalArgumentException("expected groups: {expected}");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += {width}) {{
      double time = Double.parseDouble(args[index]);
      double requestCount = Double.parseDouble(args[index + 1]);
      boolean deviceOn = Double.parseDouble(args[index + 2]) != 0.0;{hold_parse}
      System.out.println(Double.toString(
          controller.step(time, requestCount, deviceOn{call_suffix})));
    }}
  }}
}}
"""


def _trim_and_respond_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _trim_and_respond_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private double", "private double")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private long", "private long")
    members = members.replace("  private void", "private void")
    members = members.replace("  public double", "public double")
    hold_enabled = bool(config["hold_enabled"])
    variant = "have_hol=true" if hold_enabled else "have_hol=false"
    status_check = (
        "\n        || !getHold().getStatus().isOk()"
        if hold_enabled
        else ""
    )
    call_suffix = ",\n        getHold().getValue()" if hold_enabled else ""
    return f"""// Generated by BACTalk from the pinned G36 TrimAndRespond contract.
// This is the exact reviewed {variant} variant; see manifest.json.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getRequestCount().getStatus().isOk()
        || !getDeviceOn().getStatus().isOk(){status_check}) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    double result = step(
        timeSeconds,
        getRequestCount().getValue(),
        getDeviceOn().getValue(){call_suffix});
    getOut().setValue(result);
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{
    ticket.cancel();
    ticket = null;
  }}
}}

private void scheduleNext() {{
  if (ticket != null) {{
    ticket.cancel();
  }}
  ticket = Clock.schedule(
      getComponent(),
      BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS),
      BProgram.execute,
      null);
}}
"""


def _hysteresis_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.HYSTERESIS:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    return {
        "u_low": float(block.config["u_low"]),
        "u_high": float(block.config["u_high"]),
        "initial": bool(block.config.get("initial", False)),
    }


def _hysteresis_kernel_members(config: dict[str, Any]) -> str:
    return f"""  private static final double U_LOW = {_java_number(config["u_low"])};
  private static final double U_HIGH = {_java_number(config["u_high"])};
  private static final boolean INITIAL = {str(config["initial"]).lower()};

  private boolean output = INITIAL;

  private void resetControllerState() {{
    output = INITIAL;
  }}

  public boolean step(double input) {{
    if (Double.isNaN(input) || Double.isInfinite(input)) {{
      throw new IllegalArgumentException("Hysteresis input must be finite");
    }}
    output = (!output && input > U_HIGH) || (output && input >= U_LOW);
    return output;
  }}
"""


def _hysteresis_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Reals.Hysteresis kernel.
public final class {class_name} {{
{_hysteresis_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0) {{
      throw new IllegalArgumentException("expected one or more input values");
    }}
    {class_name} controller = new {class_name}();
    for (String argument : args) {{
      System.out.println(Boolean.toString(controller.step(Double.parseDouble(argument))));
    }}
  }}
}}
"""


def _hysteresis_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _hysteresis_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public boolean", "public boolean")
    return f"""// Generated by BACTalk from the pinned CDL.Reals.Hysteresis contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};

{members}
public void onStart() throws Exception {{
  resetControllerState();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    getOut().setValue(step(getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _true_false_hold_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.BOOLEAN_TRUE_FALSE_HOLD:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    return {
        "true_hold_seconds": float(block.config["true_hold_seconds"]),
        "false_hold_seconds": float(block.config["false_hold_seconds"]),
    }


def _true_false_hold_kernel_members(config: dict[str, Any]) -> str:
    true_hold = _java_number(config["true_hold_seconds"])
    false_hold = _java_number(config["false_hold_seconds"])
    return f"""  private static final double TRUE_HOLD_SECONDS = {true_hold};
  private static final double FALSE_HOLD_SECONDS = {false_hold};

  private boolean initialized = false;
  private boolean held = false;
  private double elapsed = 0.0;
  private double previousTimeSeconds = Double.NaN;

  private void resetControllerState() {{
    initialized = false;
    held = false;
    elapsed = 0.0;
    previousTimeSeconds = Double.NaN;
  }}

  public boolean step(double timeSeconds, boolean input) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)) {{
      throw new IllegalArgumentException("TrueFalseHold time must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("TrueFalseHold time must be monotonic");
    }}
    if (!initialized) {{
      initialized = true;
      held = input;
      elapsed = 0.0;
      previousTimeSeconds = timeSeconds;
      return held;
    }}
    elapsed += timeSeconds - previousTimeSeconds;
    previousTimeSeconds = timeSeconds;
    if (input != held) {{
      double required = Math.max(0.0, held ? TRUE_HOLD_SECONDS : FALSE_HOLD_SECONDS);
      if (elapsed >= required) {{
        held = input;
        elapsed = 0.0;
      }}
    }}
    return held;
  }}
"""


def _true_false_hold_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Logical.TrueFalseHold kernel.
public final class {class_name} {{
{_true_false_hold_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: time input");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      double time = Double.parseDouble(args[index]);
      boolean input = Double.parseDouble(args[index + 1]) != 0.0;
      System.out.println(Boolean.toString(controller.step(time, input)));
    }}
  }}
}}
"""


def _true_false_hold_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _true_false_hold_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private double", "private double")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public boolean", "public boolean")
    return f"""// Generated by BACTalk from the pinned CDL.Logical.TrueFalseHold contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    getOut().setValue(step(timeSeconds, getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _true_delay_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.BOOLEAN_DELAY:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if block.config.get("semantic_contract") != "CDL.Logical.TrueDelay":
        raise NiagaraProgramCodegenError(
            "boolean_delay ProgramObject generation requires the explicit "
            "CDL.Logical.TrueDelay semantic contract"
        )
    off_delay = float(block.config.get("off_delay_seconds", 0.0))
    initial = bool(block.config.get("initial", False))
    if off_delay != 0.0 or initial:
        raise NiagaraProgramCodegenError(
            "CDL.Logical.TrueDelay requires zero off delay and false initial output"
        )
    return {
        "delay_seconds": float(block.config["on_delay_seconds"]),
        "delay_on_init": bool(block.config.get("delay_on_init", False)),
        "off_delay_seconds": off_delay,
        "initial": initial,
        "semantic_contract": "CDL.Logical.TrueDelay",
    }


def _true_delay_kernel_members(config: dict[str, Any]) -> str:
    delay = _java_number(config["delay_seconds"])
    delay_on_init = str(config["delay_on_init"]).lower()
    return f"""  private static final double DELAY_SECONDS = {delay};
  private static final boolean DELAY_ON_INIT = {delay_on_init};

  private boolean initialized = false;
  private boolean previousInput = false;
  private boolean held = false;
  private double timer = 0.0;
  private double previousTimeSeconds = Double.NaN;

  private void resetControllerState() {{
    initialized = false;
    previousInput = false;
    held = false;
    timer = 0.0;
    previousTimeSeconds = Double.NaN;
  }}

  public boolean step(double timeSeconds, boolean input) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)) {{
      throw new IllegalArgumentException("TrueDelay time must be finite");
    }}
    if (DELAY_SECONDS < 0.0) {{
      throw new IllegalStateException("TrueDelay delay must be non-negative");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("TrueDelay time must be monotonic");
    }}

    boolean output;
    double nextTimer;
    if (!input) {{
      output = false;
      nextTimer = 0.0;
    }} else if (!initialized) {{
      if (DELAY_ON_INIT && DELAY_SECONDS > 0.0) {{
        output = false;
        nextTimer = 0.0;
      }} else {{
        output = true;
        nextTimer = DELAY_SECONDS;
      }}
    }} else if (held) {{
      output = true;
      nextTimer = DELAY_SECONDS;
    }} else if (!previousInput) {{
      output = DELAY_SECONDS <= 0.0;
      nextTimer = 0.0;
    }} else {{
      nextTimer = timer + timeSeconds - previousTimeSeconds;
      output = nextTimer >= DELAY_SECONDS;
    }}

    initialized = true;
    previousInput = input;
    held = output;
    timer = nextTimer;
    previousTimeSeconds = timeSeconds;
    return output;
  }}
"""


def _true_delay_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Logical.TrueDelay kernel.
public final class {class_name} {{
{_true_delay_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: time input");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      double time = Double.parseDouble(args[index]);
      boolean input = Double.parseDouble(args[index + 1]) != 0.0;
      System.out.println(Boolean.toString(controller.step(time, input)));
    }}
  }}
}}
"""


def _true_delay_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _true_delay_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private double", "private double")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public boolean", "public boolean")
    return f"""// Generated by BACTalk from the pinned CDL.Logical.TrueDelay contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    getOut().setValue(step(timeSeconds, getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _logical_latch_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.BOOLEAN_SET_RESET:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if block.config.get("semantic_contract") != "CDL.Logical.Latch":
        raise NiagaraProgramCodegenError(
            "boolean_set_reset ProgramObject generation requires the explicit "
            "CDL.Logical.Latch semantic contract"
        )
    return {"semantic_contract": "CDL.Logical.Latch"}


def _boolean_initialization_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.BOOLEAN_INITIALIZATION:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = "Buildings.Templates.Plants.Controls.Utilities.Initialization"
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "boolean_initialization ProgramObject generation requires the explicit "
            "Buildings.Templates.Plants.Controls.Utilities.Initialization semantic contract"
        )
    initial = block.config.get("initial", False)
    if not isinstance(initial, bool):
        raise NiagaraProgramCodegenError(
            "boolean_initialization ProgramObject generation requires Boolean initial"
        )
    return {"initial": initial, "semantic_contract": contract}


def _boolean_initialization_kernel_members(config: dict[str, Any]) -> str:
    initial = str(config["initial"]).lower()
    return f"""  private static final boolean INITIAL = {initial};
  private boolean first = true;

  private void resetControllerState() {{
    first = true;
  }}

  public boolean step(boolean input) {{
    if (first) {{
      first = false;
      return INITIAL;
    }}
    return input;
  }}
"""


def _boolean_initialization_standalone_source(
    class_name: str, config: dict[str, Any]
) -> str:
    return f"""// Generated by BACTalk. Exact plant Utilities.Initialization kernel.
public final class {class_name} {{
{_boolean_initialization_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0) {{
      throw new IllegalArgumentException("expected one or more Boolean inputs");
    }}
    {class_name} controller = new {class_name}();
    for (String arg : args) {{
      boolean input = Double.parseDouble(arg) != 0.0;
      System.out.println(Boolean.toString(controller.step(input)));
    }}
  }}
}}
"""


def _boolean_initialization_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _boolean_initialization_kernel_members(config)
    members = members.replace("  private static final", "private static final")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public boolean", "public boolean")
    return f"""// Generated by BACTalk from the pinned plant Initialization contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};

{members}
public void onStart() throws Exception {{
  resetControllerState();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    getOut().setValue(step(getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _logical_latch_kernel_members() -> str:
    return """  private boolean held = false;
  private boolean previousSet = false;

  private void resetControllerState() {
    held = false;
    previousSet = false;
  }

  public boolean step(boolean set, boolean clear) {
    boolean output = !clear && ((set && !previousSet) || held);
    held = output;
    previousSet = set;
    return output;
  }
"""


def _logical_latch_standalone_source(class_name: str) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Logical.Latch kernel.
public final class {class_name} {{
{_logical_latch_kernel_members()}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: set clear");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      boolean set = Double.parseDouble(args[index]) != 0.0;
      boolean clear = Double.parseDouble(args[index + 1]) != 0.0;
      System.out.println(Boolean.toString(controller.step(set, clear)));
    }}
  }}
}}
"""


def _logical_latch_program_source(execute_period_seconds: int) -> str:
    members = _logical_latch_kernel_members()
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public boolean", "public boolean")
    return f"""// Generated by BACTalk from the pinned CDL.Logical.Latch contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};

{members}
public void onStart() throws Exception {{
  resetControllerState();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getSet().getStatus().isOk() || !getClear().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    getOut().setValue(step(getSet().getValue(), getClear().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _timer_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.TIMER:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if block.config.get("semantic_contract") != "CDL.Logical.Timer":
        raise NiagaraProgramCodegenError(
            "timer ProgramObject generation requires the explicit CDL.Logical.Timer "
            "semantic contract"
        )
    return {
        "threshold_seconds": float(block.config.get("threshold_seconds", 0.0)),
        "semantic_contract": "CDL.Logical.Timer",
    }


def _timer_kernel_members(config: dict[str, Any]) -> str:
    threshold = _java_number(config["threshold_seconds"])
    return f"""  private static final double THRESHOLD_SECONDS = {threshold};

  private boolean initialized = false;
  private double entryTimeSeconds = 0.0;
  private double previousTimeSeconds = Double.NaN;
  private boolean previousInput = false;
  private boolean passed = THRESHOLD_SECONDS <= 0.0;
  private double elapsedOutput = 0.0;
  private boolean passedOutput = THRESHOLD_SECONDS <= 0.0;

  private void resetControllerState() {{
    initialized = false;
    entryTimeSeconds = 0.0;
    previousTimeSeconds = Double.NaN;
    previousInput = false;
    passed = THRESHOLD_SECONDS <= 0.0;
    elapsedOutput = 0.0;
    passedOutput = THRESHOLD_SECONDS <= 0.0;
  }}

  public void step(double timeSeconds, boolean input) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)) {{
      throw new IllegalArgumentException("Timer time must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("Timer time must be monotonic");
    }}
    double elapsed;
    if (!input || !initialized || !previousInput) {{
      elapsed = 0.0;
    }} else {{
      elapsed = timeSeconds - entryTimeSeconds;
    }}
    boolean nextPassed;
    if (input && !previousInput) {{
      nextPassed = THRESHOLD_SECONDS <= 0.0;
    }} else if (input && elapsed >= THRESHOLD_SECONDS) {{
      nextPassed = true;
    }} else if (!input && previousInput) {{
      nextPassed = false;
    }} else {{
      nextPassed = passed;
    }}
    if (input && (!initialized || !previousInput)) {{
      entryTimeSeconds = timeSeconds;
    }}
    initialized = true;
    previousTimeSeconds = timeSeconds;
    previousInput = input;
    passed = nextPassed;
    elapsedOutput = elapsed;
    passedOutput = nextPassed;
  }}

  public double elapsed() {{ return elapsedOutput; }}
  public boolean passed() {{ return passedOutput; }}
"""


def _timer_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Logical.Timer kernel.
public final class {class_name} {{
{_timer_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: time input");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      double time = Double.parseDouble(args[index]);
      boolean input = Double.parseDouble(args[index + 1]) != 0.0;
      controller.step(time, input);
      System.out.println(Double.toString(controller.elapsed()) + "," +
          Boolean.toString(controller.passed()));
    }}
  }}
}}
"""


def _timer_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _timer_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private double", "private double")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public double", "public double")
    members = members.replace("  public boolean", "public boolean")
    members = members.replace("  public void", "public void")
    return f"""// Generated by BACTalk from the pinned CDL.Logical.Timer contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getElapsed().setStatus(BStatus.NULL);
      getPassed().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    step(timeSeconds, getIn().getValue());
    getElapsed().setValue(elapsed());
    getPassed().setValue(passed());
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _timer_with_reset_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.TIMER_WITH_RESET:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "timer_with_reset ProgramObject generation requires the explicit "
            "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset semantic contract"
        )
    return {
        "threshold_seconds": float(block.config.get("threshold_seconds", 0.0)),
        "semantic_contract": contract,
    }


def _timer_with_reset_kernel_members(config: dict[str, Any]) -> str:
    threshold = _java_number(config["threshold_seconds"])
    return f"""  private static final double THRESHOLD_SECONDS = {threshold};

  private boolean initialized = false;
  private double entryTimeSeconds = 0.0;
  private double previousTimeSeconds = Double.NaN;
  private boolean previousInput = false;
  private boolean previousReset = false;
  private double elapsedOutput = 0.0;
  private boolean passedOutput = false;

  private void resetControllerState() {{
    initialized = false;
    entryTimeSeconds = 0.0;
    previousTimeSeconds = Double.NaN;
    previousInput = false;
    previousReset = false;
    elapsedOutput = 0.0;
    passedOutput = false;
  }}

  public void step(double timeSeconds, boolean input, boolean reset) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)) {{
      throw new IllegalArgumentException("TimerWithReset time must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("TimerWithReset time must be monotonic");
    }}
    if (!initialized) {{
      entryTimeSeconds = timeSeconds;
      elapsedOutput = 0.0;
      passedOutput = input && THRESHOLD_SECONDS <= 0.0;
      initialized = true;
    }} else {{
      boolean risingInput = input && !previousInput;
      boolean risingReset = reset && !previousReset;
      if (risingInput || risingReset) {{
        entryTimeSeconds = timeSeconds;
        passedOutput = input && THRESHOLD_SECONDS <= 0.0;
      }} else if (input && timeSeconds >= entryTimeSeconds + THRESHOLD_SECONDS) {{
        passedOutput = true;
      }} else if (!input && previousInput) {{
        passedOutput = false;
      }}
      elapsedOutput = input ? timeSeconds - entryTimeSeconds : 0.0;
    }}
    previousTimeSeconds = timeSeconds;
    previousInput = input;
    previousReset = reset;
  }}

  public double elapsed() {{ return elapsedOutput; }}
  public boolean passed() {{ return passedOutput; }}
"""


def _timer_with_reset_standalone_source(
    class_name: str, config: dict[str, Any]
) -> str:
    return f"""// Generated by BACTalk. Exact plant Utilities.TimerWithReset kernel.
public final class {class_name} {{
{_timer_with_reset_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 3 != 0) {{
      throw new IllegalArgumentException("expected groups: time input reset");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 3) {{
      double time = Double.parseDouble(args[index]);
      boolean input = Double.parseDouble(args[index + 1]) != 0.0;
      boolean reset = Double.parseDouble(args[index + 2]) != 0.0;
      controller.step(time, input, reset);
      System.out.println(Double.toString(controller.elapsed()) + "," +
          Boolean.toString(controller.passed()));
    }}
  }}
}}
"""


def _timer_with_reset_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _timer_with_reset_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private double", "private double")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private void", "private void")
    members = members.replace("  public double", "public double")
    members = members.replace("  public boolean", "public boolean")
    members = members.replace("  public void", "public void")
    return f"""// Generated by BACTalk from the pinned plant TimerWithReset contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk() || !getReset().getStatus().isOk()) {{
      getElapsed().setStatus(BStatus.NULL);
      getPassed().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    step(timeSeconds, getIn().getValue(), getReset().getValue());
    getElapsed().setValue(elapsed());
    getPassed().setValue(passed());
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _accumulating_timer_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.TIMER_ACCUMULATING:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = "Buildings.Controls.OBC.CDL.Logical.TimerAccumulating"
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "accumulating timer generation requires its pinned semantic contract"
        )
    return {
        "threshold_seconds": float(block.config.get("threshold_seconds", 0.0)),
        "semantic_contract": contract,
    }


def _accumulating_timer_kernel_members(config: dict[str, Any]) -> str:
    return f"""  private static final double THRESHOLD_SECONDS = {
        _java_number(config["threshold_seconds"])
    };
  private boolean initialized = false;
  private double previousTimeSeconds = Double.NaN;
  private boolean previousInput = false;
  private boolean previousReset = false;
  private double elapsedOutput = 0.0;
  private boolean passedOutput = THRESHOLD_SECONDS <= 0.0;

  private void resetControllerState() {{
    initialized = false;
    previousTimeSeconds = Double.NaN;
    previousInput = false;
    previousReset = false;
    elapsedOutput = 0.0;
    passedOutput = THRESHOLD_SECONDS <= 0.0;
  }}

  public void step(double timeSeconds, boolean input, boolean reset) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)) {{
      throw new IllegalArgumentException("TimerAccumulating time must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("TimerAccumulating time must be monotonic");
    }}
    if (!initialized) {{
      initialized = true;
    }} else if (reset && !previousReset) {{
      elapsedOutput = 0.0;
      passedOutput = THRESHOLD_SECONDS <= 0.0;
    }} else {{
      if (previousInput) {{ elapsedOutput += timeSeconds - previousTimeSeconds; }}
      if (input && elapsedOutput >= THRESHOLD_SECONDS) {{ passedOutput = true; }}
    }}
    previousTimeSeconds = timeSeconds;
    previousInput = input;
    previousReset = reset;
  }}

  public double elapsed() {{ return elapsedOutput; }}
  public boolean passed() {{ return passedOutput; }}
"""


def _accumulating_timer_standalone_source(
    class_name: str, config: dict[str, Any]
) -> str:
    return f"""// Generated by BACTalk. Exact CDL TimerAccumulating kernel.
public final class {class_name} {{
{_accumulating_timer_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 3 != 0) {{
      throw new IllegalArgumentException("expected groups: time input reset");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 3) {{
      controller.step(
          Double.parseDouble(args[index]),
          Double.parseDouble(args[index + 1]) != 0.0,
          Double.parseDouble(args[index + 2]) != 0.0);
      System.out.println(Double.toString(controller.elapsed()) + "," +
          Boolean.toString(controller.passed()));
    }}
  }}
}}
"""


def _accumulating_timer_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _accumulating_timer_kernel_members(config)
    for modifier in (
        "private static final",
        "private double",
        "private boolean",
        "private void",
        "public double",
        "public boolean",
        "public void",
    ):
        members = members.replace(f"  {modifier}", modifier)
    return f"""// Generated by BACTalk from the pinned TimerAccumulating contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk() || !getReset().getStatus().isOk()) {{
      getElapsed().setStatus(BStatus.NULL);
      getPassed().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    step(timeSeconds, getIn().getValue(), getReset().getValue());
    getElapsed().setValue(elapsed());
    getPassed().setValue(passed());
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _moving_average_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.MOVING_AVERAGE:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if block.config.get("semantic_contract") != "CDL.Reals.MovingAverage":
        raise NiagaraProgramCodegenError(
            "moving_average ProgramObject generation requires the explicit "
            "CDL.Reals.MovingAverage semantic contract"
        )
    return {
        "window_seconds": float(block.config["window_seconds"]),
        "semantic_contract": "CDL.Reals.MovingAverage",
        "checkpoint_capacity": 64,
    }


def _moving_average_kernel_members(config: dict[str, Any]) -> str:
    window = _java_number(config["window_seconds"])
    return f"""  private static final double WINDOW_SECONDS = {window};
  private static final double MIN_WINDOW_SECONDS = 1.0e-5;
  private static final int CAPACITY = 64;

  private double mu = 0.0;
  private double startTimeSeconds = 0.0;
  private double previousTimeSeconds = Double.NaN;
  private final double[] checkpointTimes = new double[CAPACITY];
  private final double[] checkpointMus = new double[CAPACITY];
  private int checkpointHead = 0;
  private int checkpointLength = 0;

  private void resetControllerState() {{
    mu = 0.0;
    startTimeSeconds = 0.0;
    previousTimeSeconds = Double.NaN;
    checkpointHead = 0;
    checkpointLength = 0;
  }}

  private int physicalIndex(int logicalIndex) {{
    return (checkpointHead + logicalIndex) % CAPACITY;
  }}

  private double checkpointTime(int logicalIndex) {{
    return checkpointTimes[physicalIndex(logicalIndex)];
  }}

  private double checkpointMu(int logicalIndex) {{
    return checkpointMus[physicalIndex(logicalIndex)];
  }}

  private void prune(double cutoff) {{
    while (checkpointLength > 1 && checkpointTime(1) <= cutoff) {{
      checkpointHead = (checkpointHead + 1) % CAPACITY;
      checkpointLength -= 1;
    }}
  }}

  private void store(double timeSeconds, double muNow) {{
    if (checkpointLength > 0) {{
      int last = physicalIndex(checkpointLength - 1);
      if (Double.doubleToRawLongBits(checkpointTimes[last]) ==
          Double.doubleToRawLongBits(timeSeconds)) {{
        checkpointMus[last] = muNow;
        return;
      }}
    }}
    if (checkpointLength == CAPACITY) {{
      checkpointHead = (checkpointHead + 1) % CAPACITY;
      checkpointLength -= 1;
    }}
    int slot = physicalIndex(checkpointLength);
    checkpointTimes[slot] = timeSeconds;
    checkpointMus[slot] = muNow;
    checkpointLength += 1;
  }}

  private double muAt(double target, double timeSeconds, double muNow) {{
    if (checkpointLength == 0) {{ return muNow; }}
    double firstTime = checkpointTime(0);
    double firstMu = checkpointMu(0);
    if (target <= firstTime) {{ return firstMu; }}
    double previousTime = firstTime;
    double previousMu = firstMu;
    for (int index = 1; index < checkpointLength; index += 1) {{
      double nextTime = checkpointTime(index);
      double nextMu = checkpointMu(index);
      if (target <= nextTime) {{
        double denominator = nextTime - previousTime;
        return denominator == 0.0
            ? nextMu
            : previousMu + (nextMu - previousMu) *
                ((target - previousTime) / denominator);
      }}
      previousTime = nextTime;
      previousMu = nextMu;
    }}
    if (target <= timeSeconds) {{
      double denominator = timeSeconds - previousTime;
      return denominator == 0.0
          ? muNow
          : previousMu + (muNow - previousMu) *
              ((target - previousTime) / denominator);
    }}
    return muNow;
  }}

  public double step(double timeSeconds, double input) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)
        || Double.isNaN(input) || Double.isInfinite(input)) {{
      throw new IllegalArgumentException("MovingAverage inputs must be finite");
    }}
    boolean firstTick = Double.isNaN(previousTimeSeconds);
    if (!firstTick && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("MovingAverage time must be monotonic");
    }}
    double delta = Math.max(WINDOW_SECONDS, MIN_WINDOW_SECONDS);
    double start = firstTick ? timeSeconds : startTimeSeconds;
    double dt = firstTick ? 0.0 : timeSeconds - previousTimeSeconds;
    double muNow = mu + input * dt;
    double target = timeSeconds - delta;
    double delayedMu = muAt(target, timeSeconds, muNow);
    double denominator;
    if (timeSeconds >= start + delta) {{
      double retainedLow = checkpointLength > 0 ? checkpointTime(0) : start;
      double low = Math.max(Math.max(target, retainedLow), start);
      denominator = Math.max(timeSeconds - low, MIN_WINDOW_SECONDS);
    }} else {{
      denominator = timeSeconds - start + 1.0e-3;
    }}
    double output = (muNow - delayedMu) / denominator;
    if (firstTick) {{ startTimeSeconds = timeSeconds; }}
    prune(target);
    store(timeSeconds, muNow);
    mu = muNow;
    previousTimeSeconds = timeSeconds;
    return output;
  }}
"""


def _moving_average_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Reals.MovingAverage kernel.
public final class {class_name} {{
{_moving_average_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: time input");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      double time = Double.parseDouble(args[index]);
      double input = Double.parseDouble(args[index + 1]);
      System.out.println(Double.toString(controller.step(time, input)));
    }}
  }}
}}
"""


def _moving_average_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _moving_average_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private final", "private final")
    members = members.replace("  private double", "private double")
    members = members.replace("  private int", "private int")
    members = members.replace("  private void", "private void")
    members = members.replace("  public double", "public double")
    return f"""// Generated by BACTalk from the pinned CDL.Reals.MovingAverage contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    getOut().setValue(step(timeSeconds, getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _assert_warning_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.BOOLEAN_ASSERT_WARNING:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    message = block.config.get("message")
    if not isinstance(message, str) or not message:
        raise NiagaraProgramCodegenError("Assert warning requires a non-empty message")
    return {
        "message": message,
        "severity": "warning",
        "repeat_while_false": True,
    }


def _assert_warning_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    message = _java_string(config["message"])
    return f"""// Generated by BACTalk. Exact CDL.Utilities.Assert qualification kernel.
public final class {class_name} {{
  private static final String MESSAGE = {message};

  public boolean step(boolean condition) {{
    if (!condition) {{ System.out.println(MESSAGE); }}
    return condition;
  }}

  public static void main(String[] args) {{
    {class_name} assertion = new {class_name}();
    for (String argument : args) {{
      assertion.step(Double.parseDouble(argument) != 0.0);
    }}
  }}
}}
"""


def _assert_warning_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    message = _java_string(config["message"])
    return f"""// Generated by BACTalk from the pinned CDL.Utilities.Assert contract.
// This warning sink deliberately has no signal output. A false input logs on every execution.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private static final String MESSAGE = {message};

public void onStart() throws Exception {{
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (getCondition().getStatus().isOk() && !getCondition().getValue()) {{
      java.util.logging.Logger.getLogger("bactalk.g36.assert").warning(MESSAGE);
    }}
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _falling_edge_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.BOOLEAN_FALLING_EDGE:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    return {"pre_u_start": bool(block.config.get("pre_u_start", False))}


def _falling_edge_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    initial = str(config["pre_u_start"]).lower()
    return f"""// Generated by BACTalk. Exact CDL.Logical.FallingEdge qualification kernel.
public final class {class_name} {{
  private boolean previous = {initial};

  public boolean step(boolean current) {{
    boolean output = previous && !current;
    previous = current;
    return output;
  }}

  public static void main(String[] args) {{
    {class_name} edge = new {class_name}();
    for (String argument : args) {{
      System.out.println(Boolean.toString(edge.step(Double.parseDouble(argument) != 0.0)));
    }}
  }}
}}
"""


def _falling_edge_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    initial = str(config["pre_u_start"]).lower()
    return f"""// Generated by BACTalk from the pinned CDL.Logical.FallingEdge contract.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private static final boolean PRE_U_START = {initial};
private boolean previous = PRE_U_START;

private boolean step(boolean current) {{
  boolean output = previous && !current;
  previous = current;
  return output;
}}

public void onStart() throws Exception {{
  previous = PRE_U_START;
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    getOut().setValue(step(getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _boolean_pre_host_tick_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.BOOLEAN_PRE_HOST_TICK:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if (
        block.config.get("semantic_contract") != "CDL.Logical.Pre"
        or block.config.get("execution_profile") != "host_tick_v1"
    ):
        raise NiagaraProgramCodegenError(
            "boolean_pre_host_tick generation requires the explicit CDL.Logical.Pre "
            "host_tick_v1 semantic contract"
        )
    return {
        "initial": bool(block.config.get("initial", False)),
        "semantic_contract": "CDL.Logical.Pre",
        "execution_profile": "host_tick_v1",
    }


def _boolean_pre_host_tick_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    initial = str(config["initial"]).lower()
    return f"""// Generated by BACTalk. CDL.Logical.Pre host_tick_v1 qualification kernel.
public final class {class_name} {{
  private boolean previous = {initial};

  public boolean step(boolean current) {{
    boolean output = previous;
    previous = current;
    return output;
  }}

  public static void main(String[] args) {{
    {class_name} memory = new {class_name}();
    for (String argument : args) {{
      System.out.println(Boolean.toString(memory.step(Double.parseDouble(argument) != 0.0)));
    }}
  }}
}}
"""


def _boolean_pre_host_tick_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    initial = str(config["initial"]).lower()
    return f"""// Generated by BACTalk from CDL.Logical.Pre under host_tick_v1.
// This is a sampled Niagara scan projection, not Modelica same-time event iteration.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private static final boolean PRE_U_START = {initial};
private boolean previous = PRE_U_START;

private boolean step(boolean current) {{
  boolean output = previous;
  previous = current;
  return output;
}}

public void onStart() throws Exception {{
  previous = PRE_U_START;
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    getOut().setValue(step(getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _numeric_sampler_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.NUMERIC_SAMPLER:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if block.config.get("semantic_contract") != "CDL.Discrete.Sampler":
        raise NiagaraProgramCodegenError(
            "numeric_sampler generation requires the explicit CDL.Discrete.Sampler contract"
        )
    return {
        "sample_period_seconds": float(block.config["sample_period_seconds"]),
        "semantic_contract": "CDL.Discrete.Sampler",
    }


def _numeric_sampler_kernel_members(config: dict[str, Any]) -> str:
    period = _java_number(config["sample_period_seconds"])
    return f"""  private static final double SAMPLE_PERIOD_SECONDS = {period};
  private boolean initialized = false;
  private double held = 0.0;
  private double t0 = 0.0;
  private long lastIndex = 0L;
  private double previousTimeSeconds = Double.NaN;

  public double step(double timeSeconds, double input) {{
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(input)) {{
      throw new IllegalArgumentException("Sampler inputs must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("Sampler time must be monotonic");
    }}
    if (!initialized) {{
      t0 = Math.floor(timeSeconds / SAMPLE_PERIOD_SECONDS) * SAMPLE_PERIOD_SECONDS;
      lastIndex = (long) Math.floor((timeSeconds - t0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      held = input;
      initialized = true;
    }} else {{
      long index = (long) Math.floor(
          (timeSeconds - t0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      if (index > lastIndex) {{
        held = input;
        lastIndex = index;
      }}
    }}
    previousTimeSeconds = timeSeconds;
    return held;
  }}
"""


def _numeric_sampler_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Discrete.Sampler kernel.
public final class {class_name} {{
{_numeric_sampler_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: time input");
    }}
    {class_name} sampler = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      System.out.println(Double.toString(sampler.step(
          Double.parseDouble(args[index]), Double.parseDouble(args[index + 1]))));
    }}
  }}
}}
"""


def _numeric_sampler_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _numeric_sampler_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private double", "private double")
    members = members.replace("  private long", "private long")
    members = members.replace("  public double", "public double")
    return f"""// Generated by BACTalk from the pinned CDL.Discrete.Sampler contract.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{ getOut().setStatus(BStatus.NULL); return; }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    getOut().setValue(step(timeSeconds, getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _triggered_sampler_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.NUMERIC_LATCH:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if block.config.get("semantic_contract") != "CDL.Discrete.TriggeredSampler":
        raise NiagaraProgramCodegenError(
            "numeric_latch generation requires the explicit CDL.Discrete.TriggeredSampler contract"
        )
    return {
        "initial": float(block.config.get("initial", 0.0)),
        "semantic_contract": "CDL.Discrete.TriggeredSampler",
    }


def _triggered_sampler_kernel_members(config: dict[str, Any]) -> str:
    initial = _java_number(config["initial"])
    return f"""  private static final double INITIAL = {initial};
  private double held = INITIAL;
  private boolean previousTrigger = false;

  public double step(double input, boolean trigger) {{
    if (!Double.isFinite(input)) {{
      throw new IllegalArgumentException("TriggeredSampler input must be finite");
    }}
    if (trigger && !previousTrigger) {{ held = input; }}
    previousTrigger = trigger;
    return held;
  }}
"""


def _triggered_sampler_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Discrete.TriggeredSampler kernel.
public final class {class_name} {{
{_triggered_sampler_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: input trigger");
    }}
    {class_name} sampler = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      System.out.println(Double.toString(sampler.step(
          Double.parseDouble(args[index]),
          Double.parseDouble(args[index + 1]) != 0.0)));
    }}
  }}
}}
"""


def _triggered_sampler_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _triggered_sampler_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private double", "private double")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  public double", "public double")
    return f"""// Generated by BACTalk from the pinned CDL.Discrete.TriggeredSampler contract.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};

{members}
public void onStart() throws Exception {{
  held = INITIAL;
  previousTrigger = false;
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk() || !getClock().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    getOut().setValue(step(getIn().getValue(), getClock().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _numeric_unit_delay_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.NUMERIC_UNIT_DELAY:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if block.config.get("semantic_contract") != "CDL.Discrete.UnitDelay":
        raise NiagaraProgramCodegenError(
            "numeric_unit_delay generation requires the explicit CDL.Discrete.UnitDelay contract"
        )
    return {
        "sample_period_seconds": float(block.config["sample_period_seconds"]),
        "initial": float(block.config.get("initial", 0.0)),
        "semantic_contract": "CDL.Discrete.UnitDelay",
    }


def _numeric_unit_delay_kernel_members(config: dict[str, Any]) -> str:
    period = _java_number(config["sample_period_seconds"])
    initial = _java_number(config["initial"])
    return f"""  private static final double SAMPLE_PERIOD_SECONDS = {period};
  private static final double INITIAL = {initial};
  private boolean initialized = false;
  private double held = INITIAL;
  private double staged = INITIAL;
  private double t0 = 0.0;
  private long lastIndex = 0L;
  private double previousTimeSeconds = Double.NaN;

  public double step(double timeSeconds, double input) {{
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(input)) {{
      throw new IllegalArgumentException("UnitDelay inputs must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("UnitDelay time must be monotonic");
    }}
    if (!initialized) {{
      t0 = Math.floor(timeSeconds / SAMPLE_PERIOD_SECONDS) * SAMPLE_PERIOD_SECONDS;
      lastIndex = (long) Math.floor((timeSeconds - t0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
      double boundary = t0 + lastIndex * SAMPLE_PERIOD_SECONDS;
      staged = Math.abs(timeSeconds - boundary) <= 1.0e-9 ? input : INITIAL;
      initialized = true;
      previousTimeSeconds = timeSeconds;
      return INITIAL;
    }}
    long index = (long) Math.floor(
        (timeSeconds - t0) / SAMPLE_PERIOD_SECONDS + 1.0e-9);
    if (index > lastIndex) {{
      held = staged;
      staged = input;
      lastIndex = index;
    }}
    previousTimeSeconds = timeSeconds;
    return held;
  }}
"""


def _numeric_unit_delay_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact CDL.Discrete.UnitDelay kernel.
public final class {class_name} {{
{_numeric_unit_delay_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 2 != 0) {{
      throw new IllegalArgumentException("expected groups: time input");
    }}
    {class_name} delay = new {class_name}();
    for (int index = 0; index < args.length; index += 2) {{
      System.out.println(Double.toString(delay.step(
          Double.parseDouble(args[index]), Double.parseDouble(args[index + 1]))));
    }}
  }}
}}
"""


def _numeric_unit_delay_program_source(config: dict[str, Any], execute_period_seconds: int) -> str:
    members = _numeric_unit_delay_kernel_members(config).replace(
        "  private static final", "private static final"
    )
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private double", "private double")
    members = members.replace("  private long", "private long")
    members = members.replace("  public double", "public double")
    return f"""// Generated by BACTalk from the pinned CDL.Discrete.UnitDelay contract.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{ getOut().setStatus(BStatus.NULL); return; }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    getOut().setValue(step(timeSeconds, getIn().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _plant_equipment_availability_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.PLANT_EQUIPMENT_AVAILABILITY:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = (
        "Buildings.Templates.Plants.Controls.StagingRotation.EquipmentAvailability"
    )
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "plant equipment availability generation requires its pinned semantic contract"
        )
    return {
        "off_time_seconds": float(block.config["off_time_seconds"]),
        "have_heating": bool(block.config["have_heating"]),
        "have_cooling": bool(block.config["have_cooling"]),
        "semantic_contract": contract,
    }


def _plant_equipment_availability_kernel_members(config: dict[str, Any]) -> str:
    off_time = _java_number(config["off_time_seconds"])
    return f"""  private static final double OFF_TIME_SECONDS = {off_time};
  private String mode = "available";
  private double offSinceSeconds = Double.NaN;
  private double previousTimeSeconds = Double.NaN;

  private void resetControllerState() {{
    mode = "available";
    offSinceSeconds = Double.NaN;
    previousTimeSeconds = Double.NaN;
  }}

  public void step(
      double timeSeconds,
      boolean enableHeating,
      boolean enableCooling,
      boolean available) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds)) {{
      throw new IllegalArgumentException("EquipmentAvailability time must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("EquipmentAvailability time must be monotonic");
    }}
    for (int iteration = 0; iteration < 5; iteration++) {{
      String nextMode = mode;
      if (mode.equals("available")) {{
        if (!available) nextMode = "unavailable";
        else if (enableCooling) nextMode = "cooling";
        else if (enableHeating) nextMode = "heating";
      }} else if (mode.equals("heating")) {{
        if (!enableHeating) {{
          nextMode = "off";
          offSinceSeconds = timeSeconds;
        }} else if (!available) nextMode = "unavailable";
      }} else if (mode.equals("cooling")) {{
        if (!enableCooling) {{
          nextMode = "off";
          offSinceSeconds = timeSeconds;
        }} else if (!available) nextMode = "unavailable";
      }} else if (mode.equals("off")) {{
        if (timeSeconds - offSinceSeconds >= OFF_TIME_SECONDS) nextMode = "available";
      }} else if (mode.equals("unavailable") && available) {{
        nextMode = "available";
      }}
      if (nextMode.equals(mode)) break;
      mode = nextMode;
    }}
    previousTimeSeconds = timeSeconds;
  }}

  public boolean heatingAvailable() {{
    return mode.equals("available") || mode.equals("heating");
  }}

  public boolean coolingAvailable() {{
    return mode.equals("available") || mode.equals("cooling");
  }}
"""


def _plant_equipment_availability_standalone_source(
    class_name: str, config: dict[str, Any]
) -> str:
    return f"""// Generated by BACTalk. Exact plant EquipmentAvailability kernel.
public final class {class_name} {{
{_plant_equipment_availability_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 4 != 0) {{
      throw new IllegalArgumentException(
          "expected groups: time enableHeating enableCooling available");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 4) {{
      controller.step(
          Double.parseDouble(args[index]),
          Double.parseDouble(args[index + 1]) != 0.0,
          Double.parseDouble(args[index + 2]) != 0.0,
          Double.parseDouble(args[index + 3]) != 0.0);
      System.out.println(Boolean.toString(controller.heatingAvailable()) + "," +
          Boolean.toString(controller.coolingAvailable()));
    }}
  }}
}}
"""


def _plant_equipment_availability_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _plant_equipment_availability_kernel_members(config)
    members = members.replace("  private static final", "private static final")
    members = members.replace("  private String", "private String")
    members = members.replace("  private double", "private double")
    members = members.replace("  private void", "private void")
    members = members.replace("  public void", "public void")
    members = members.replace("  public boolean", "public boolean")
    return f"""// Generated by BACTalk from the pinned plant EquipmentAvailability contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getEnableHeating().getStatus().isOk() ||
        !getEnableCooling().getStatus().isOk() ||
        !getAvailable().getStatus().isOk()) {{
      getHeatingAvailable().setStatus(BStatus.NULL);
      getCoolingAvailable().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    step(
        timeSeconds,
        getEnableHeating().getValue(),
        getEnableCooling().getValue(),
        getAvailable().getValue());
    getHeatingAvailable().setValue(heatingAvailable());
    getCoolingAvailable().setValue(coolingAvailable());
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _plant_enable_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.PLANT_ENABLE:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = "Buildings.Templates.Plants.Controls.Enabling.Enable"
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "plant enable generation requires its pinned semantic contract"
        )
    return {
        "application": str(block.config["application"]),
        "have_input_schedule": bool(block.config["have_input_schedule"]),
        "schedule": [
            [float(row[0]), float(row[1])] for row in block.config["schedule"]
        ],
        "outdoor_lockout": float(block.config["outdoor_lockout"]),
        "outdoor_lockout_hysteresis": float(
            block.config["outdoor_lockout_hysteresis"]
        ),
        "ignored_requests": int(block.config["ignored_requests"]),
        "minimum_state_time_seconds": float(
            block.config["minimum_state_time_seconds"]
        ),
        "low_request_time_seconds": float(block.config["low_request_time_seconds"]),
        "semantic_contract": contract,
    }


def _plant_enable_kernel_members(config: dict[str, Any]) -> str:
    times = ", ".join(_java_number(row[0]) for row in config["schedule"])
    values = ", ".join(_java_number(row[1]) for row in config["schedule"])
    return f"""  private static final boolean HEATING = {
        str(config["application"] == "Heating").lower()
    };
  private static final boolean HAVE_INPUT_SCHEDULE = {
        str(config["have_input_schedule"]).lower()
    };
  private static final double[] SCHEDULE_TIMES = new double[] {{{times}}};
  private static final double[] SCHEDULE_VALUES = new double[] {{{values}}};
  private static final double OUTDOOR_LOCKOUT = {
        _java_number(config["outdoor_lockout"])
    };
  private static final double OUTDOOR_HYSTERESIS = {
        _java_number(config["outdoor_lockout_hysteresis"])
    };
  private static final int IGNORED_REQUESTS = {config["ignored_requests"]};
  private static final double MINIMUM_STATE_TIME_SECONDS = {
        _java_number(config["minimum_state_time_seconds"])
    };
  private static final double LOW_REQUEST_TIME_SECONDS = {
        _java_number(config["low_request_time_seconds"])
    };

  private boolean initialized = false;
  private boolean enabled = false;
  private double disabledSinceSeconds = 0.0;
  private double enabledSinceSeconds = Double.NaN;
  private double lowRequestSinceSeconds = Double.NaN;
  private double previousTimeSeconds = Double.NaN;

  private void resetControllerState() {{
    initialized = false;
    enabled = false;
    disabledSinceSeconds = 0.0;
    enabledSinceSeconds = Double.NaN;
    lowRequestSinceSeconds = Double.NaN;
    previousTimeSeconds = Double.NaN;
  }}

  private boolean internalSchedule(double scheduleTimeSeconds) {{
    double period = SCHEDULE_TIMES[SCHEDULE_TIMES.length - 1];
    double phase = period > 0.0
        ? ((scheduleTimeSeconds % period) + period) % period
        : scheduleTimeSeconds;
    boolean result = SCHEDULE_VALUES[0] != 0.0;
    for (int index = 0; index < SCHEDULE_TIMES.length; index++) {{
      if (phase < SCHEDULE_TIMES[index]) break;
      result = SCHEDULE_VALUES[index] != 0.0;
    }}
    return result;
  }}

  public boolean step(
      double timeSeconds,
      double scheduleTimeSeconds,
      boolean scheduleInput,
      double requestCount,
      double outdoorTemperature) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds) ||
        Double.isNaN(scheduleTimeSeconds) || Double.isInfinite(scheduleTimeSeconds) ||
        Double.isNaN(requestCount) || Double.isInfinite(requestCount) ||
        Double.isNaN(outdoorTemperature) || Double.isInfinite(outdoorTemperature)) {{
      throw new IllegalArgumentException("PlantEnable inputs must be finite");
    }}
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {{
      throw new IllegalArgumentException("PlantEnable time must be monotonic");
    }}
    boolean lowRequest = requestCount <= IGNORED_REQUESTS;
    if (!initialized) {{
      disabledSinceSeconds = timeSeconds;
      lowRequestSinceSeconds = lowRequest ? timeSeconds : Double.NaN;
      initialized = true;
    }} else if (lowRequest) {{
      if (Double.isNaN(lowRequestSinceSeconds)) lowRequestSinceSeconds = timeSeconds;
    }} else {{
      lowRequestSinceSeconds = Double.NaN;
    }}
    boolean lowRequestPassed = !Double.isNaN(lowRequestSinceSeconds) &&
        timeSeconds - lowRequestSinceSeconds >= LOW_REQUEST_TIME_SECONDS;
    boolean scheduleEnabled = HAVE_INPUT_SCHEDULE
        ? scheduleInput : internalSchedule(scheduleTimeSeconds);
    boolean outdoorEnable = HEATING
        ? outdoorTemperature < OUTDOOR_LOCKOUT
        : outdoorTemperature > OUTDOOR_LOCKOUT;
    boolean outdoorDisable = HEATING
        ? outdoorTemperature > OUTDOOR_LOCKOUT + OUTDOOR_HYSTERESIS
        : outdoorTemperature < OUTDOOR_LOCKOUT - OUTDOOR_HYSTERESIS;
    if (!enabled) {{
      boolean disabledLongEnough =
          timeSeconds - disabledSinceSeconds >= MINIMUM_STATE_TIME_SECONDS;
      if (disabledLongEnough && scheduleEnabled &&
          requestCount > IGNORED_REQUESTS && outdoorEnable) {{
        enabled = true;
        enabledSinceSeconds = timeSeconds;
      }}
    }} else {{
      boolean enabledLongEnough =
          timeSeconds - enabledSinceSeconds >= MINIMUM_STATE_TIME_SECONDS;
      if (enabledLongEnough && (!scheduleEnabled || lowRequestPassed || outdoorDisable)) {{
        enabled = false;
        disabledSinceSeconds = timeSeconds;
      }}
    }}
    previousTimeSeconds = timeSeconds;
    return enabled;
  }}
"""


def _plant_enable_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact plant Enabling.Enable kernel.
public final class {class_name} {{
{_plant_enable_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 5 != 0) {{
      throw new IllegalArgumentException(
          "expected groups: time scheduleTime schedule requests outdoorTemperature");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 5) {{
      System.out.println(Boolean.toString(controller.step(
          Double.parseDouble(args[index]),
          Double.parseDouble(args[index + 1]),
          Double.parseDouble(args[index + 2]) != 0.0,
          Double.parseDouble(args[index + 3]),
          Double.parseDouble(args[index + 4]))));
    }}
  }}
}}
"""


def _plant_enable_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _plant_enable_kernel_members(config)
    members = members.replace("  private static final", "private static final")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private double", "private double")
    members = members.replace("  private void", "private void")
    members = members.replace("  public boolean", "public boolean")
    return f"""// Generated by BACTalk from the pinned plant Enabling.Enable contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getScheduleEnabled().getStatus().isOk() ||
        !getRequestCount().getStatus().isOk() ||
        !getOutdoorTemperature().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    java.util.Calendar calendar = java.util.Calendar.getInstance();
    double scheduleTimeSeconds =
        calendar.get(java.util.Calendar.HOUR_OF_DAY) * 3600.0 +
        calendar.get(java.util.Calendar.MINUTE) * 60.0 +
        calendar.get(java.util.Calendar.SECOND) +
        calendar.get(java.util.Calendar.MILLISECOND) / 1000.0;
    getOut().setValue(step(
        timeSeconds,
        scheduleTimeSeconds,
        getScheduleEnabled().getValue(),
        getRequestCount().getValue(),
        getOutdoorTemperature().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _numeric_changed_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.NUMERIC_CHANGED:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    return {
        "initial": float(block.config.get("initial", 0.0)),
        "semantic_contract": str(
            block.config.get("semantic_contract", "CDL.Numeric.Change")
        ),
    }


def _numeric_changed_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    initial = _java_number(config["initial"])
    return f"""// Generated by BACTalk. Exact numeric change detector.
public final class {class_name} {{
  private double previous = {initial};

  public boolean step(double current) {{
    if (Double.isNaN(current) || Double.isInfinite(current)) {{
      throw new IllegalArgumentException("change-detector input must be finite");
    }}
    boolean changed = current != previous;
    previous = current;
    return changed;
  }}

  public static void main(String[] args) {{
    {class_name} detector = new {class_name}();
    for (String argument : args) {{
      System.out.println(Boolean.toString(detector.step(Double.parseDouble(argument))));
    }}
  }}
}}
"""


def _numeric_changed_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    initial = _java_number(config["initial"])
    return f"""// Generated by BACTalk from an exact numeric Change contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private double previous = {initial};

public void onStart() throws Exception {{
  previous = {initial};
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getIn().getStatus().isOk()) {{
      getOut().setStatus(BStatus.NULL);
      return;
    }}
    double current = getIn().getValue();
    getOut().setValue(current != previous);
    previous = current;
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _plant_stage_completion_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.PLANT_STAGE_COMPLETION:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = (
        "Buildings.Templates.Plants.Controls.StagingRotation.StageCompletion"
    )
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "stage completion generation requires its pinned semantic contract"
        )
    return {
        "equipment_count": int(block.config["equipment_count"]),
        "semantic_contract": contract,
    }


def _plant_stage_completion_kernel_members(config: dict[str, Any]) -> str:
    return f"""  private static final int EQUIPMENT_COUNT = {config["equipment_count"]};
  private static final long MAXIMUM_MASK = (1L << EQUIPMENT_COUNT) - 1L;
  private long previousCommandMask = 0L;
  private boolean previousAnyChange = false;
  private boolean previousPreAnyChange = false;
  private long previousStage = 0L;
  private boolean previousStageChange = false;
  private boolean changeLatch = false;
  private boolean stageLatch = false;
  private boolean completedOutput = false;

  private void resetControllerState() {{
    previousCommandMask = 0L;
    previousAnyChange = false;
    previousPreAnyChange = false;
    previousStage = 0L;
    previousStageChange = false;
    changeLatch = false;
    stageLatch = false;
    completedOutput = false;
  }}

  private long exactInteger(double value, long maximum, String label) {{
    if (Double.isNaN(value) || Double.isInfinite(value) ||
        value < 0.0 || value > maximum || value != Math.rint(value)) {{
      throw new IllegalArgumentException(label + " must be a bounded integer");
    }}
    return (long) value;
  }}

  public void step(double commandMaskValue, double statusMaskValue, double stageValue) {{
    long commandMask = exactInteger(commandMaskValue, MAXIMUM_MASK, "commandMask");
    long statusMask = exactInteger(statusMaskValue, MAXIMUM_MASK, "statusMask");
    long stage = exactInteger(stageValue, Long.MAX_VALUE, "stage");
    boolean anyChange = commandMask != previousCommandMask;
    boolean preAnyChange = previousAnyChange;
    boolean stageChange = stage != previousStage;
    boolean newChangeLatch = !stageChange &&
        ((preAnyChange && !previousPreAnyChange) || changeLatch);
    boolean allMatch = commandMask == statusMask;
    boolean changeAndMatch = newChangeLatch && allMatch;
    boolean newStageLatch = !changeAndMatch &&
        ((stageChange && !previousStageChange) || stageLatch);
    completedOutput = stageLatch && !newStageLatch;
    previousCommandMask = commandMask;
    previousAnyChange = anyChange;
    previousPreAnyChange = preAnyChange;
    previousStage = stage;
    previousStageChange = stageChange;
    changeLatch = newChangeLatch;
    stageLatch = newStageLatch;
  }}

  public boolean inProgress() {{ return stageLatch; }}
  public boolean completed() {{ return completedOutput; }}
"""


def _plant_stage_completion_standalone_source(
    class_name: str, config: dict[str, Any]
) -> str:
    return f"""// Generated by BACTalk. Exact plant stage-completion kernel.
public final class {class_name} {{
{_plant_stage_completion_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 3 != 0) {{
      throw new IllegalArgumentException("expected groups: commandMask statusMask stage");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 3) {{
      controller.step(
          Double.parseDouble(args[index]),
          Double.parseDouble(args[index + 1]),
          Double.parseDouble(args[index + 2]));
      System.out.println(Boolean.toString(controller.inProgress()) + "," +
          Boolean.toString(controller.completed()));
    }}
  }}
}}
"""


def _plant_stage_completion_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _plant_stage_completion_kernel_members(config)
    for modifier in (
        "private static final",
        "private long",
        "private boolean",
        "private void",
        "public void",
        "public boolean",
    ):
        members = members.replace(f"  {modifier}", modifier)
    return f"""// Generated by BACTalk from the pinned StageCompletion contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};

{members}
public void onStart() throws Exception {{
  resetControllerState();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getCommandMask().getStatus().isOk() ||
        !getStatusMask().getStatus().isOk() ||
        !getStage().getStatus().isOk()) {{
      getInProgress().setStatus(BStatus.NULL);
      getCompleted().setStatus(BStatus.NULL);
      return;
    }}
    step(
        getCommandMask().getValue(),
        getStatusMask().getValue(),
        getStage().getValue());
    getInProgress().setValue(inProgress());
    getCompleted().setValue(completed());
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _plant_stage_index_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.PLANT_STAGE_INDEX:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = "Buildings.Templates.Plants.Controls.Utilities.StageIndex"
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "stage index generation requires its pinned semantic contract"
        )
    return {
        "stage_count": int(block.config["stage_count"]),
        "minimum_runtime_seconds": float(block.config["minimum_runtime_seconds"]),
        "semantic_contract": contract,
    }


def _plant_stage_index_kernel_members(config: dict[str, Any]) -> str:
    return f"""  private static final int STAGE_COUNT = {config["stage_count"]};
  private static final long MAXIMUM_MASK = (1L << STAGE_COUNT) - 1L;
  private static final double MINIMUM_RUNTIME = {
        _java_number(config["minimum_runtime_seconds"])
    };
  private int stage = 0;
  private double enteredAt = 0.0;
  private double previousTime = Double.NEGATIVE_INFINITY;

  private void resetControllerState() {{
    stage = 0;
    enteredAt = 0.0;
    previousTime = Double.NEGATIVE_INFINITY;
  }}

  private long exactMask(double value) {{
    if (Double.isNaN(value) || Double.isInfinite(value) ||
        value < 0.0 || value > MAXIMUM_MASK || value != Math.rint(value)) {{
      throw new IllegalArgumentException("availabilityMask must be a bounded integer");
    }}
    return (long) value;
  }}

  private boolean available(long mask, int candidate) {{
    return (mask & (1L << (candidate - 1))) != 0L;
  }}

  private int firstAvailable(long mask) {{
    for (int candidate = 1; candidate <= STAGE_COUNT; candidate++) {{
      if (available(mask, candidate)) {{ return candidate; }}
    }}
    return 0;
  }}

  private int nextHigher(long mask, int current) {{
    for (int candidate = current + 1; candidate <= STAGE_COUNT; candidate++) {{
      if (available(mask, candidate)) {{ return candidate; }}
    }}
    return 0;
  }}

  private int nextLower(long mask, int current) {{
    for (int candidate = current - 1; candidate >= 1; candidate--) {{
      if (available(mask, candidate)) {{ return candidate; }}
    }}
    return 0;
  }}

  public int step(
      double timeSeconds,
      boolean leadEnable,
      boolean stageUp,
      boolean stageDown,
      double availabilityMaskValue) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds) ||
        timeSeconds < previousTime) {{
      throw new IllegalArgumentException("stage-index time must be finite and monotonic");
    }}
    long availabilityMask = exactMask(availabilityMaskValue);
    int nextStage = stage;
    if (stage == 0) {{
      int first = firstAvailable(availabilityMask);
      if (leadEnable && first > 0) {{ nextStage = first; }}
    }} else {{
      int higher = nextHigher(availabilityMask, stage);
      int lower = nextLower(availabilityMask, stage);
      boolean activeAvailable = available(availabilityMask, stage);
      boolean runtimeMet = timeSeconds - enteredAt >= MINIMUM_RUNTIME;
      if (!activeAvailable && higher > 0) {{
        nextStage = higher;
      }} else if (runtimeMet && !leadEnable) {{
        nextStage = 0;
      }} else if (runtimeMet && stageUp && higher > 0) {{
        nextStage = higher;
      }} else if (runtimeMet && stageDown && lower > 0) {{
        nextStage = lower;
      }}
    }}
    if (nextStage != stage) {{ enteredAt = timeSeconds; }}
    stage = nextStage;
    previousTime = timeSeconds;
    return stage;
  }}
"""


def _plant_stage_index_standalone_source(
    class_name: str, config: dict[str, Any]
) -> str:
    return f"""// Generated by BACTalk. Exact plant stage-index state machine.
public final class {class_name} {{
{_plant_stage_index_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 5 != 0) {{
      throw new IllegalArgumentException(
          "expected groups: time leadEnable stageUp stageDown availabilityMask");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 5) {{
      System.out.println(Integer.toString(controller.step(
          Double.parseDouble(args[index]),
          Double.parseDouble(args[index + 1]) != 0.0,
          Double.parseDouble(args[index + 2]) != 0.0,
          Double.parseDouble(args[index + 3]) != 0.0,
          Double.parseDouble(args[index + 4]))));
    }}
  }}
}}
"""


def _plant_stage_index_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _plant_stage_index_kernel_members(config)
    for modifier in (
        "private static final",
        "private int",
        "private double",
        "private long",
        "private boolean",
        "private void",
        "public int",
    ):
        members = members.replace(f"  {modifier}", modifier)
    return f"""// Generated by BACTalk from the pinned StageIndex contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getLeadEnable().getStatus().isOk() ||
        !getStageUp().getStatus().isOk() ||
        !getStageDown().getStatus().isOk() ||
        !getAvailabilityMask().getStatus().isOk()) {{
      getStage().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    getStage().setValue(step(
        timeSeconds,
        getLeadEnable().getValue(),
        getStageUp().getValue(),
        getStageDown().getValue(),
        getAvailabilityMask().getValue()));
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _plant_hrc_enable_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.PLANT_HRC_ENABLE:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = "Buildings.Templates.Plants.Controls.HeatRecoveryChillers.Enable"
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "HRC enable generation requires its pinned semantic contract"
        )
    return {
        "minimum_chilled_supply_temperature": float(
            block.config["minimum_chilled_supply_temperature"]
        ),
        "maximum_heating_supply_temperature": float(
            block.config["maximum_heating_supply_temperature"]
        ),
        "minimum_cooling_capacity": float(block.config["minimum_cooling_capacity"]),
        "minimum_heating_capacity": float(block.config["minimum_heating_capacity"]),
        "minimum_state_time_seconds": float(
            block.config["minimum_state_time_seconds"]
        ),
        "sufficient_load_time_seconds": float(
            block.config["sufficient_load_time_seconds"]
        ),
        "temperature_limit_1_time_seconds": float(
            block.config["temperature_limit_1_time_seconds"]
        ),
        "temperature_limit_2_time_seconds": float(
            block.config["temperature_limit_2_time_seconds"]
        ),
        "semantic_contract": contract,
    }


def _plant_hrc_enable_kernel_members(config: dict[str, Any]) -> str:
    return f"""  private static final double MIN_CHILLED_TEMPERATURE = {
        _java_number(config["minimum_chilled_supply_temperature"])
    };
  private static final double MAX_HEATING_TEMPERATURE = {
        _java_number(config["maximum_heating_supply_temperature"])
    };
  private static final double MIN_COOLING_CAPACITY = {
        _java_number(config["minimum_cooling_capacity"])
    };
  private static final double MIN_HEATING_CAPACITY = {
        _java_number(config["minimum_heating_capacity"])
    };
  private static final double MINIMUM_STATE_TIME = {
        _java_number(config["minimum_state_time_seconds"])
    };
  private static final double SUFFICIENT_LOAD_TIME = {
        _java_number(config["sufficient_load_time_seconds"])
    };
  private static final double TEMPERATURE_TIME_1 = {
        _java_number(config["temperature_limit_1_time_seconds"])
    };
  private static final double TEMPERATURE_TIME_2 = {
        _java_number(config["temperature_limit_2_time_seconds"])
    };
  private final boolean[] timerSeen = new boolean[9];
  private final boolean[] timerPrevious = new boolean[9];
  private final boolean[] timerPassed = new boolean[9];
  private final double[] timerEntry = new double[9];
  private boolean highCoolingLoad = false;
  private boolean highHeatingLoad = false;
  private boolean lowCoolingLoad = false;
  private boolean lowHeatingLoad = false;
  private boolean previousHrcStatus = false;
  private boolean previousAllEnable = false;
  private boolean previousDisable = false;
  private boolean latchOutput = false;
  private boolean enableOutput = false;
  private boolean setModeOutput = false;
  private boolean firstStep = true;
  private double delayStarted = Double.NaN;
  private double previousTime = Double.NEGATIVE_INFINITY;

  private void resetControllerState() {{
    java.util.Arrays.fill(timerSeen, false);
    java.util.Arrays.fill(timerPrevious, false);
    java.util.Arrays.fill(timerPassed, false);
    java.util.Arrays.fill(timerEntry, 0.0);
    highCoolingLoad = false;
    highHeatingLoad = false;
    lowCoolingLoad = false;
    lowHeatingLoad = false;
    previousHrcStatus = false;
    previousAllEnable = false;
    previousDisable = false;
    latchOutput = false;
    enableOutput = false;
    setModeOutput = false;
    firstStep = true;
    delayStarted = Double.NaN;
    previousTime = Double.NEGATIVE_INFINITY;
  }}

  private boolean timer(int index, boolean active, double threshold, double timeSeconds) {{
    if (!timerSeen[index]) {{
      timerSeen[index] = true;
      timerEntry[index] = timeSeconds;
      timerPrevious[index] = false;
      timerPassed[index] = threshold <= 0.0;
    }}
    if (active && !timerPrevious[index]) {{
      timerEntry[index] = timeSeconds;
      timerPassed[index] = threshold <= 0.0;
    }} else if (active && timeSeconds >= timerEntry[index] + threshold) {{
      timerPassed[index] = true;
    }} else if (!active) {{
      timerPassed[index] = false;
    }}
    timerPrevious[index] = active;
    return timerPassed[index];
  }}

  public void step(
      double timeSeconds,
      boolean coolingPlantEnable,
      boolean heatingPlantEnable,
      boolean hrcStatus,
      double coolingLoad,
      double heatingLoad,
      double chilledLeavingTemperature,
      double heatingLeavingTemperature,
      boolean coolingMode) {{
    if (Double.isNaN(timeSeconds) || Double.isInfinite(timeSeconds) ||
        Double.isNaN(coolingLoad) || Double.isInfinite(coolingLoad) ||
        Double.isNaN(heatingLoad) || Double.isInfinite(heatingLoad) ||
        Double.isNaN(chilledLeavingTemperature) ||
        Double.isInfinite(chilledLeavingTemperature) ||
        Double.isNaN(heatingLeavingTemperature) ||
        Double.isInfinite(heatingLeavingTemperature)) {{
      throw new IllegalArgumentException("HRC enable inputs must be finite");
    }}
    if (timeSeconds < previousTime) {{
      throw new IllegalArgumentException("HRC enable time must be monotonic");
    }}
    boolean wasFirstStep = firstStep;
    boolean previousEnable = enableOutput;
    double coolingHysteresis = 1.0e-4 * MIN_COOLING_CAPACITY;
    double heatingHysteresis = 1.0e-4 * MIN_HEATING_CAPACITY;
    highCoolingLoad = coolingHysteresis < 1.0e-10
        ? coolingLoad > MIN_COOLING_CAPACITY
        : (!highCoolingLoad ? coolingLoad > MIN_COOLING_CAPACITY
                            : coolingLoad > MIN_COOLING_CAPACITY - coolingHysteresis);
    highHeatingLoad = heatingHysteresis < 1.0e-10
        ? heatingLoad > MIN_HEATING_CAPACITY
        : (!highHeatingLoad ? heatingLoad > MIN_HEATING_CAPACITY
                            : heatingLoad > MIN_HEATING_CAPACITY - heatingHysteresis);
    boolean coolingPlantPassed =
        timer(0, coolingPlantEnable, MINIMUM_STATE_TIME, timeSeconds);
    boolean heatingPlantPassed =
        timer(1, heatingPlantEnable, MINIMUM_STATE_TIME, timeSeconds);
    boolean disabledPassed =
        timer(2, !previousEnable, MINIMUM_STATE_TIME, timeSeconds);
    boolean coolingLoadPassed =
        timer(3, highCoolingLoad, SUFFICIENT_LOAD_TIME, timeSeconds);
    boolean heatingLoadPassed =
        timer(4, highHeatingLoad, SUFFICIENT_LOAD_TIME, timeSeconds);
    boolean allEnable = coolingPlantPassed && heatingPlantPassed && disabledPassed &&
        coolingLoadPassed && heatingLoadPassed;

    lowCoolingLoad = coolingHysteresis < 1.0e-10
        ? coolingLoad < MIN_COOLING_CAPACITY
        : (!lowCoolingLoad ? coolingLoad < MIN_COOLING_CAPACITY
                           : coolingLoad < MIN_COOLING_CAPACITY + coolingHysteresis);
    // Exact pinned source behavior: QChiWatReq_flow drives both low-load comparators.
    lowHeatingLoad = heatingHysteresis < 1.0e-10
        ? coolingLoad < MIN_HEATING_CAPACITY
        : (!lowHeatingLoad ? coolingLoad < MIN_HEATING_CAPACITY
                           : coolingLoad < MIN_HEATING_CAPACITY + heatingHysteresis);
    boolean fallingEdge = previousHrcStatus && !hrcStatus;
    boolean lowLoadCycleOff = fallingEdge && (lowCoolingLoad || lowHeatingLoad);

    boolean chilledTrip1 = timer(
        5, chilledLeavingTemperature < MIN_CHILLED_TEMPERATURE + 1.0,
        TEMPERATURE_TIME_1, timeSeconds);
    boolean chilledTrip2 = timer(
        6, chilledLeavingTemperature < MIN_CHILLED_TEMPERATURE,
        TEMPERATURE_TIME_2, timeSeconds);
    boolean heatingTrip1 = timer(
        7, heatingLeavingTemperature > MAX_HEATING_TEMPERATURE - 1.5,
        TEMPERATURE_TIME_1, timeSeconds);
    boolean heatingTrip2 = timer(
        8, heatingLeavingTemperature > MAX_HEATING_TEMPERATURE,
        TEMPERATURE_TIME_2, timeSeconds);
    boolean disable = !coolingPlantEnable || !heatingPlantEnable || lowLoadCycleOff ||
        (previousEnable && !coolingMode && (chilledTrip1 || chilledTrip2)) ||
        (previousEnable && coolingMode && (heatingTrip1 || heatingTrip2));

    boolean newLatch = latchOutput;
    if (wasFirstStep) {{
      newLatch = !disable && allEnable;
    }} else if ((disable && !previousDisable) ||
               (allEnable && !previousAllEnable)) {{
      newLatch = !disable && allEnable;
    }}
    setModeOutput = newLatch && !latchOutput;
    if (wasFirstStep) {{
      enableOutput = newLatch;
      delayStarted = newLatch ? timeSeconds : Double.NaN;
    }} else if (!newLatch) {{
      enableOutput = false;
      delayStarted = Double.NaN;
    }} else if (!latchOutput) {{
      enableOutput = false;
      delayStarted = timeSeconds;
    }} else if (!enableOutput && !Double.isNaN(delayStarted) &&
               timeSeconds - delayStarted >= 5.0) {{
      enableOutput = true;
    }}

    previousHrcStatus = hrcStatus;
    previousAllEnable = allEnable;
    previousDisable = disable;
    latchOutput = newLatch;
    firstStep = false;
    previousTime = timeSeconds;
  }}

  public boolean enable() {{ return enableOutput; }}
  public boolean setMode() {{ return setModeOutput; }}
"""


def _plant_hrc_enable_standalone_source(
    class_name: str, config: dict[str, Any]
) -> str:
    return f"""// Generated by BACTalk. Exact heat-recovery chiller enable kernel.
public final class {class_name} {{
{_plant_hrc_enable_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 9 != 0) {{
      throw new IllegalArgumentException(
          "expected groups: time coolingPlant heatingPlant hrcStatus coolingLoad " +
          "heatingLoad chilledLeaving heatingLeaving coolingMode");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 9) {{
      controller.step(
          Double.parseDouble(args[index]),
          Double.parseDouble(args[index + 1]) != 0.0,
          Double.parseDouble(args[index + 2]) != 0.0,
          Double.parseDouble(args[index + 3]) != 0.0,
          Double.parseDouble(args[index + 4]),
          Double.parseDouble(args[index + 5]),
          Double.parseDouble(args[index + 6]),
          Double.parseDouble(args[index + 7]),
          Double.parseDouble(args[index + 8]) != 0.0);
      System.out.println(Boolean.toString(controller.enable()) + "," +
          Boolean.toString(controller.setMode()));
    }}
  }}
}}
"""


def _plant_hrc_enable_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _plant_hrc_enable_kernel_members(config)
    for modifier in (
        "private static final",
        "private final",
        "private boolean",
        "private double",
        "private void",
        "public void",
        "public boolean",
    ):
        members = members.replace(f"  {modifier}", modifier)
    return f"""// Generated by BACTalk from the pinned HRC Enable contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};
private long programStartedMillis = 0L;

{members}
public void onStart() throws Exception {{
  resetControllerState();
  programStartedMillis = System.currentTimeMillis();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getCoolingPlantEnable().getStatus().isOk() ||
        !getHeatingPlantEnable().getStatus().isOk() ||
        !getHrcStatus().getStatus().isOk() ||
        !getCoolingLoad().getStatus().isOk() ||
        !getHeatingLoad().getStatus().isOk() ||
        !getChilledLeavingTemperature().getStatus().isOk() ||
        !getHeatingLeavingTemperature().getStatus().isOk() ||
        !getCoolingMode().getStatus().isOk()) {{
      getEnable().setStatus(BStatus.NULL);
      getSetMode().setStatus(BStatus.NULL);
      return;
    }}
    double timeSeconds = Math.max(
        0.0, (System.currentTimeMillis() - programStartedMillis) / 1000.0);
    step(
        timeSeconds,
        getCoolingPlantEnable().getValue(),
        getHeatingPlantEnable().getValue(),
        getHrcStatus().getValue(),
        getCoolingLoad().getValue(),
        getHeatingLoad().getValue(),
        getChilledLeavingTemperature().getValue(),
        getHeatingLeavingTemperature().getValue(),
        getCoolingMode().getValue());
    getEnable().setValue(enable());
    getSetMode().setValue(setMode());
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _plant_hrc_mode_config(block: Block) -> dict[str, Any]:
    if block.kind != BlockKind.PLANT_HRC_MODE_CONTROL:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    contract = (
        "Buildings.Templates.Plants.Controls.HeatRecoveryChillers.ModeControl"
    )
    if block.config.get("semantic_contract") != contract:
        raise NiagaraProgramCodegenError(
            "HRC mode control generation requires its pinned semantic contract"
        )
    return {
        "heating_cop": float(block.config["heating_cop"]),
        "semantic_contract": contract,
    }


def _plant_hrc_mode_kernel_members(config: dict[str, Any]) -> str:
    return f"""  private static final double HEATING_COP = {
        _java_number(config["heating_cop"])
    };
  private boolean comparison = false;
  private boolean coolingModeOutput = false;
  private double supplySetpointOutput = 0.0;

  private void resetControllerState() {{
    comparison = false;
    coolingModeOutput = false;
    supplySetpointOutput = 0.0;
  }}

  public void step(
      boolean setMode,
      double coolingLoad,
      double heatingLoad,
      double chilledSetpoint,
      double heatingSetpoint) {{
    if (Double.isNaN(coolingLoad) || Double.isInfinite(coolingLoad) ||
        Double.isNaN(heatingLoad) || Double.isInfinite(heatingLoad) ||
        Double.isNaN(chilledSetpoint) || Double.isInfinite(chilledSetpoint) ||
        Double.isNaN(heatingSetpoint) || Double.isInfinite(heatingSetpoint)) {{
      throw new IllegalArgumentException("HRC mode inputs must be finite");
    }}
    double evaporatorLoad = heatingLoad * (1.0 - 1.0 / HEATING_COP);
    comparison = (!comparison && coolingLoad < evaporatorLoad) ||
        (comparison && coolingLoad < evaporatorLoad + 1.0);
    if (setMode) coolingModeOutput = comparison;
    supplySetpointOutput = coolingModeOutput ? chilledSetpoint : heatingSetpoint;
  }}

  public boolean coolingMode() {{ return coolingModeOutput; }}
  public double supplySetpoint() {{ return supplySetpointOutput; }}
"""


def _plant_hrc_mode_standalone_source(class_name: str, config: dict[str, Any]) -> str:
    return f"""// Generated by BACTalk. Exact heat-recovery chiller mode kernel.
public final class {class_name} {{
{_plant_hrc_mode_kernel_members(config)}
  public static void main(String[] args) {{
    if (args.length == 0 || args.length % 5 != 0) {{
      throw new IllegalArgumentException(
          "expected groups: setMode coolingLoad heatingLoad chilledSetpoint heatingSetpoint");
    }}
    {class_name} controller = new {class_name}();
    for (int index = 0; index < args.length; index += 5) {{
      controller.step(
          Double.parseDouble(args[index]) != 0.0,
          Double.parseDouble(args[index + 1]),
          Double.parseDouble(args[index + 2]),
          Double.parseDouble(args[index + 3]),
          Double.parseDouble(args[index + 4]));
      System.out.println(Boolean.toString(controller.coolingMode()) + "," +
          Double.toString(controller.supplySetpoint()));
    }}
  }}
}}
"""


def _plant_hrc_mode_program_source(
    config: dict[str, Any], execute_period_seconds: int
) -> str:
    members = _plant_hrc_mode_kernel_members(config)
    members = members.replace("  private static final", "private static final")
    members = members.replace("  private boolean", "private boolean")
    members = members.replace("  private double", "private double")
    members = members.replace("  private void", "private void")
    members = members.replace("  public void", "public void")
    members = members.replace("  public boolean", "public boolean")
    members = members.replace("  public double", "public double")
    return f"""// Generated by BACTalk from the pinned HRC ModeControl contract.
// Paste/import this as Niagara ProgramObject source with the slots in slots.json.
Clock.Ticket ticket;
private static final int EXECUTE_PERIOD_SECONDS = {execute_period_seconds};

{members}
public void onStart() throws Exception {{
  resetControllerState();
  scheduleNext();
}}

public void onExecute() throws Exception {{
  try {{
    if (!getSetMode().getStatus().isOk() ||
        !getCoolingLoad().getStatus().isOk() ||
        !getHeatingLoad().getStatus().isOk() ||
        !getChilledSetpoint().getStatus().isOk() ||
        !getHeatingSetpoint().getStatus().isOk()) {{
      getCoolingMode().setStatus(BStatus.NULL);
      getSupplySetpoint().setStatus(BStatus.NULL);
      return;
    }}
    step(
        getSetMode().getValue(),
        getCoolingLoad().getValue(),
        getHeatingLoad().getValue(),
        getChilledSetpoint().getValue(),
        getHeatingSetpoint().getValue());
    getCoolingMode().setValue(coolingMode());
    getSupplySetpoint().setValue(supplySetpoint());
  }} finally {{
    scheduleNext();
  }}
}}

public void onStop() throws Exception {{
  if (ticket != null) {{ ticket.cancel(); ticket = null; }}
}}

private void scheduleNext() {{
  if (ticket != null) {{ ticket.cancel(); }}
  ticket = Clock.schedule(
      getComponent(), BRelTime.makeSeconds(EXECUTE_PERIOD_SECONDS), BProgram.execute, null);
}}
"""


def _program_assets(
    block: Block, execute_period_seconds: int, digest: str
) -> tuple[dict[str, Any], str, str, str, dict[str, Any], dict[str, Any]]:
    outputs: list[tuple[str, str]] | None = None
    if block.kind == BlockKind.PID_WITH_RESET:
        config = _pid_config(block)
        class_name = f"G36PidWithReset_{digest[:12]}"
        source = _pid_program_source(config, execute_period_seconds)
        kernel = _pid_standalone_source(class_name, config)
        inputs = [
            ("setpoint", "b:StatusNumeric"),
            ("measurement", "b:StatusNumeric"),
            ("trigger", "b:StatusBoolean"),
        ]
        output_type = "b:StatusNumeric"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Reals.PIDWithReset",
            "runtime_oracle": "Open Control Engine",
            "recurrence": (
                "emit prior state, clamp output, rising-edge integrator reset, Ni "
                "back-calculation, implicit-Euler derivative filter"
            ),
        }
    elif block.kind in {
        BlockKind.TRIM_AND_RESPOND,
        BlockKind.TRIM_AND_RESPOND_HOLD,
    }:
        config = _trim_and_respond_config(block)
        hold_enabled = bool(config["hold_enabled"])
        class_stem = "G36TrimAndRespondHold" if hold_enabled else "G36TrimAndRespond"
        class_name = f"{class_stem}_{digest[:12]}"
        source = _trim_and_respond_program_source(config, execute_period_seconds)
        kernel = _trim_and_respond_standalone_source(class_name, config)
        inputs = [
            ("request_count", "b:StatusNumeric"),
            ("device_on", "b:StatusBoolean"),
        ]
        if hold_enabled:
            inputs.append(("hold", "b:StatusBoolean"))
        output_type = "b:StatusNumeric"
        contract = {
            "standard": "Buildings.Controls.OBC.ASHRAE.G36.Generic.TrimAndRespond",
            "variant": f"have_hol={str(hold_enabled).lower()}",
            "runtime_oracle": (
                "Open Control Engine expanded pinned-source trajectory"
                if hold_enabled
                else "Open Control Engine golden-generator fixture"
            ),
            "recurrence": (
                "true-delay plus sample period, sampled request count, unit-delay "
                "feedback, capped response, bounded setpoint, device-off reset"
                + (
                    ", minimum hold duration, and sample-boundary release"
                    if hold_enabled
                    else ""
                )
            ),
        }
    elif block.kind == BlockKind.HYSTERESIS:
        config = _hysteresis_config(block)
        class_name = f"CdlHysteresis_{digest[:12]}"
        source = _hysteresis_program_source(config, execute_period_seconds)
        kernel = _hysteresis_standalone_source(class_name, config)
        inputs = [("in", "b:StatusNumeric")]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Reals.Hysteresis",
            "runtime_oracle": "Open Control Engine",
            "recurrence": "strict threshold crossings with in-band prior-output hold",
        }
    elif block.kind == BlockKind.BOOLEAN_TRUE_FALSE_HOLD:
        config = _true_false_hold_config(block)
        class_name = f"CdlTrueFalseHold_{digest[:12]}"
        source = _true_false_hold_program_source(config, execute_period_seconds)
        kernel = _true_false_hold_standalone_source(class_name, config)
        inputs = [("in", "b:StatusBoolean")]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Logical.TrueFalseHold",
            "runtime_oracle": "Open Control Engine",
            "recurrence": "initial input feedthrough followed by minimum true/false dwell",
        }
    elif block.kind == BlockKind.BOOLEAN_DELAY:
        config = _true_delay_config(block)
        class_name = f"CdlTrueDelay_{digest[:12]}"
        source = _true_delay_program_source(config, execute_period_seconds)
        kernel = _true_delay_standalone_source(class_name, config)
        inputs = [("in", "b:StatusBoolean")]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Logical.TrueDelay",
            "runtime_oracle": "Open Control Engine",
            "recurrence": (
                "immediate false, optional initial-on delay, immediate initial-on "
                "feedthrough when delayOnInit=false, continuous rising-edge timer"
            ),
        }
    elif block.kind == BlockKind.BOOLEAN_INITIALIZATION:
        config = _boolean_initialization_config(block)
        class_name = f"PlantInitialization_{digest[:12]}"
        source = _boolean_initialization_program_source(config, execute_period_seconds)
        kernel = _boolean_initialization_standalone_source(class_name, config)
        inputs = [("in", "b:StatusBoolean")]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": "Buildings.Templates.Plants.Controls.Utilities.Initialization",
            "runtime_oracle": "pinned Modelica initial() equation",
            "recurrence": (
                "emit yIni on the first evaluation after start, then pass the input "
                "through on every subsequent evaluation"
            ),
        }
    elif block.kind == BlockKind.BOOLEAN_SET_RESET:
        config = _logical_latch_config(block)
        class_name = f"CdlLogicalLatch_{digest[:12]}"
        source = _logical_latch_program_source(execute_period_seconds)
        kernel = _logical_latch_standalone_source(class_name)
        inputs = [
            ("set", "b:StatusBoolean"),
            ("clear", "b:StatusBoolean"),
        ]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Logical.Latch",
            "runtime_oracle": "Open Control Engine",
            "recurrence": (
                "clear-dominant hold, set only on rising edge, clear while set requires "
                "a new set edge"
            ),
        }
    elif block.kind == BlockKind.TIMER:
        config = _timer_config(block)
        class_name = f"CdlLogicalTimer_{digest[:12]}"
        source = _timer_program_source(config, execute_period_seconds)
        kernel = _timer_standalone_source(class_name, config)
        inputs = [("in", "b:StatusBoolean")]
        outputs = [
            ("elapsed", "b:StatusNumeric"),
            ("passed", "b:StatusBoolean"),
        ]
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Logical.Timer",
            "runtime_oracle": "Open Control Engine",
            "recurrence": (
                "elapsed time from stored rising-edge timestamp with a threshold latch "
                "that clears only on a falling edge"
            ),
        }
    elif block.kind == BlockKind.TIMER_WITH_RESET:
        config = _timer_with_reset_config(block)
        class_name = f"PlantTimerWithReset_{digest[:12]}"
        source = _timer_with_reset_program_source(config, execute_period_seconds)
        kernel = _timer_with_reset_standalone_source(class_name, config)
        inputs = [
            ("in", "b:StatusBoolean"),
            ("reset", "b:StatusBoolean"),
        ]
        outputs = [
            ("elapsed", "b:StatusNumeric"),
            ("passed", "b:StatusBoolean"),
        ]
        contract = {
            "standard": (
                "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
            ),
            "runtime_oracle": "pinned Modelica when-equation recurrence",
            "recurrence": (
                "restart elapsed time on input or reset rising edge, clear passed on "
                "input falling edge, and assert passed at the configured threshold"
            ),
        }
    elif block.kind == BlockKind.TIMER_ACCUMULATING:
        config = _accumulating_timer_config(block)
        class_name = f"CdlTimerAccumulating_{digest[:12]}"
        source = _accumulating_timer_program_source(config, execute_period_seconds)
        kernel = _accumulating_timer_standalone_source(class_name, config)
        inputs = [
            ("in", "b:StatusBoolean"),
            ("reset", "b:StatusBoolean"),
        ]
        outputs = [
            ("elapsed", "b:StatusNumeric"),
            ("passed", "b:StatusBoolean"),
        ]
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned CDL TimerAccumulating when-equation",
            "recurrence": (
                "accumulate prior-interval true time, hold while false, reset on the "
                "reset rising edge, and latch threshold passage"
            ),
        }
    elif block.kind == BlockKind.MOVING_AVERAGE:
        config = _moving_average_config(block)
        class_name = f"CdlMovingAverage_{digest[:12]}"
        source = _moving_average_program_source(config, execute_period_seconds)
        kernel = _moving_average_standalone_source(class_name, config)
        inputs = [("in", "b:StatusNumeric")]
        output_type = "b:StatusNumeric"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Reals.MovingAverage",
            "runtime_oracle": "Open Control Engine",
            "checkpoint_capacity": 64,
            "recurrence": (
                "forward-Euler integral with variable-step delayed-integral "
                "interpolation and bounded checkpoint history"
            ),
        }
    elif block.kind == BlockKind.BOOLEAN_ASSERT_WARNING:
        config = _assert_warning_config(block)
        class_name = f"CdlAssertWarning_{digest[:12]}"
        source = _assert_warning_program_source(config, execute_period_seconds)
        kernel = _assert_warning_standalone_source(class_name, config)
        inputs = [("condition", "b:StatusBoolean")]
        outputs = []
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Utilities.Assert",
            "runtime_oracle": "Open Control Engine",
            "recurrence": "warning on every evaluation whose Boolean condition is false",
            "signal_outputs": 0,
        }
    elif block.kind == BlockKind.BOOLEAN_FALLING_EDGE:
        config = _falling_edge_config(block)
        class_name = f"CdlFallingEdge_{digest[:12]}"
        source = _falling_edge_program_source(config, execute_period_seconds)
        kernel = _falling_edge_standalone_source(class_name, config)
        inputs = [("in", "b:StatusBoolean")]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Logical.FallingEdge",
            "runtime_oracle": "Open Control Engine",
            "recurrence": "true for exactly one evaluation on each true-to-false transition",
        }
    elif block.kind == BlockKind.BOOLEAN_PRE_HOST_TICK:
        config = _boolean_pre_host_tick_config(block)
        class_name = f"CdlBooleanPreHostTick_{digest[:12]}"
        source = _boolean_pre_host_tick_program_source(config, execute_period_seconds)
        kernel = _boolean_pre_host_tick_standalone_source(class_name, config)
        inputs = [("in", "b:StatusBoolean")]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Logical.Pre",
            "execution_profile": "host_tick_v1",
            "runtime_oracle": "Open Control Engine host-call behavior",
            "recurrence": "emit prior scan input, then store current input for the next scan",
            "limitation": "not Modelica same-time event iteration",
        }
    elif block.kind == BlockKind.NUMERIC_SAMPLER:
        config = _numeric_sampler_config(block)
        class_name = f"CdlNumericSampler_{digest[:12]}"
        source = _numeric_sampler_program_source(config, execute_period_seconds)
        kernel = _numeric_sampler_standalone_source(class_name, config)
        inputs = [("in", "b:StatusNumeric")]
        output_type = "b:StatusNumeric"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Discrete.Sampler",
            "runtime_oracle": "Open Control Engine",
            "recurrence": (
                "sample the input at fixed-period boundaries and hold the sampled "
                "value between boundaries"
            ),
        }
    elif block.kind == BlockKind.NUMERIC_LATCH:
        config = _triggered_sampler_config(block)
        class_name = f"CdlTriggeredSampler_{digest[:12]}"
        source = _triggered_sampler_program_source(config, execute_period_seconds)
        kernel = _triggered_sampler_standalone_source(class_name, config)
        inputs = [
            ("in", "b:StatusNumeric"),
            ("clock", "b:StatusBoolean"),
        ]
        output_type = "b:StatusNumeric"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler",
            "runtime_oracle": "Open Control Engine",
            "recurrence": "latch the input only on each false-to-true trigger transition",
        }
    elif block.kind == BlockKind.NUMERIC_UNIT_DELAY:
        config = _numeric_unit_delay_config(block)
        class_name = f"CdlNumericUnitDelay_{digest[:12]}"
        source = _numeric_unit_delay_program_source(config, execute_period_seconds)
        kernel = _numeric_unit_delay_standalone_source(class_name, config)
        inputs = [("in", "b:StatusNumeric")]
        output_type = "b:StatusNumeric"
        contract = {
            "standard": "Buildings.Controls.OBC.CDL.Discrete.UnitDelay",
            "runtime_oracle": "Open Control Engine",
            "recurrence": (
                "emit the prior sampled value and stage the current value at each "
                "fixed-period boundary"
            ),
        }
    elif block.kind == BlockKind.NUMERIC_CHANGED:
        config = _numeric_changed_config(block)
        class_name = f"CdlNumericChange_{digest[:12]}"
        source = _numeric_changed_program_source(config, execute_period_seconds)
        kernel = _numeric_changed_standalone_source(class_name, config)
        inputs = [("in", "b:StatusNumeric")]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned CDL Change equation",
            "recurrence": "compare current numeric input with prior scan input, then store it",
        }
    elif block.kind == BlockKind.PLANT_EQUIPMENT_AVAILABILITY:
        config = _plant_equipment_availability_config(block)
        class_name = f"PlantEquipmentAvailability_{digest[:12]}"
        source = _plant_equipment_availability_program_source(
            config, execute_period_seconds
        )
        kernel = _plant_equipment_availability_standalone_source(class_name, config)
        inputs = [
            ("enableHeating", "b:StatusBoolean"),
            ("enableCooling", "b:StatusBoolean"),
            ("available", "b:StatusBoolean"),
        ]
        outputs = [
            ("heatingAvailable", "b:StatusBoolean"),
            ("coolingAvailable", "b:StatusBoolean"),
        ]
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned Modelica StateGraph source and validation fixture",
            "recurrence": (
                "initial all-modes availability; active-mode exclusion; unavailable-state "
                "recovery; and minimum off-time before opposite-mode availability"
            ),
        }
    elif block.kind == BlockKind.PLANT_ENABLE:
        config = _plant_enable_config(block)
        class_name = f"PlantEnable_{digest[:12]}"
        source = _plant_enable_program_source(config, execute_period_seconds)
        kernel = _plant_enable_standalone_source(class_name, config)
        inputs = [
            ("scheduleEnabled", "b:StatusBoolean"),
            ("requestCount", "b:StatusNumeric"),
            ("outdoorTemperature", "b:StatusNumeric"),
        ]
        output_type = "b:StatusBoolean"
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned Modelica block network and validation trajectories",
            "recurrence": (
                "application-specific outdoor lockout with hysteresis, request and schedule "
                "gating, low-request delay, and minimum enabled/disabled dwell"
            ),
        }
    elif block.kind == BlockKind.PLANT_STAGE_COMPLETION:
        config = _plant_stage_completion_config(block)
        class_name = f"PlantStageCompletion_{digest[:12]}"
        source = _plant_stage_completion_program_source(
            config, execute_period_seconds
        )
        kernel = _plant_stage_completion_standalone_source(class_name, config)
        inputs = [
            ("commandMask", "b:StatusNumeric"),
            ("statusMask", "b:StatusNumeric"),
            ("stage", "b:StatusNumeric"),
        ]
        outputs = [
            ("inProgress", "b:StatusBoolean"),
            ("completed", "b:StatusBoolean"),
        ]
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned Modelica change/pre/latch block network",
            "equipment_count": config["equipment_count"],
            "vector_encoding": "lossless integer bitmask",
            "recurrence": (
                "one-scan delayed command-change detection; stage-change and command-change "
                "clear-dominant latches; all-command/status match; one-scan completion pulse"
            ),
        }
    elif block.kind == BlockKind.PLANT_STAGE_INDEX:
        config = _plant_stage_index_config(block)
        class_name = f"PlantStageIndex_{digest[:12]}"
        source = _plant_stage_index_program_source(config, execute_period_seconds)
        kernel = _plant_stage_index_standalone_source(class_name, config)
        inputs = [
            ("leadEnable", "b:StatusBoolean"),
            ("stageUp", "b:StatusBoolean"),
            ("stageDown", "b:StatusBoolean"),
            ("availabilityMask", "b:StatusNumeric"),
        ]
        outputs = [("stage", "b:StatusNumeric")]
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned Modelica StateGraph network",
            "stage_count": config["stage_count"],
            "vector_encoding": "lossless integer bitmask",
            "recurrence": (
                "stage-zero lead enable; minimum-runtime-gated up, down, and disable "
                "transitions; unavailable-stage skipping and immediate higher-stage recovery"
            ),
        }
    elif block.kind == BlockKind.PLANT_HRC_ENABLE:
        config = _plant_hrc_enable_config(block)
        class_name = f"PlantHrcEnable_{digest[:12]}"
        source = _plant_hrc_enable_program_source(config, execute_period_seconds)
        kernel = _plant_hrc_enable_standalone_source(class_name, config)
        inputs = [
            ("coolingPlantEnable", "b:StatusBoolean"),
            ("heatingPlantEnable", "b:StatusBoolean"),
            ("hrcStatus", "b:StatusBoolean"),
            ("coolingLoad", "b:StatusNumeric"),
            ("heatingLoad", "b:StatusNumeric"),
            ("chilledLeavingTemperature", "b:StatusNumeric"),
            ("heatingLeavingTemperature", "b:StatusNumeric"),
            ("coolingMode", "b:StatusBoolean"),
        ]
        outputs = [
            ("enable", "b:StatusBoolean"),
            ("setMode", "b:StatusBoolean"),
        ]
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned Modelica block network and validation trajectory",
            "recurrence": (
                "plant/load qualification timers; exact source-connected high/low load "
                "hysteresis; falling-edge cycle-off; mode-specific two-level temperature "
                "trips; clear-dominant latch; setting edge; five-second true delay"
            ),
            "source_connection_note": (
                "The pinned source connects QChiWatReq_flow to both low-load comparators; "
                "the generated recurrence preserves that behavior for traceability."
            ),
        }
    elif block.kind == BlockKind.PLANT_HRC_MODE_CONTROL:
        config = _plant_hrc_mode_config(block)
        class_name = f"PlantHrcModeControl_{digest[:12]}"
        source = _plant_hrc_mode_program_source(config, execute_period_seconds)
        kernel = _plant_hrc_mode_standalone_source(class_name, config)
        inputs = [
            ("setMode", "b:StatusBoolean"),
            ("coolingLoad", "b:StatusNumeric"),
            ("heatingLoad", "b:StatusNumeric"),
            ("chilledSetpoint", "b:StatusNumeric"),
            ("heatingSetpoint", "b:StatusNumeric"),
        ]
        outputs = [
            ("coolingMode", "b:StatusBoolean"),
            ("supplySetpoint", "b:StatusNumeric"),
        ]
        contract = {
            "standard": config["semantic_contract"],
            "runtime_oracle": "pinned Modelica equations and Less hysteresis recurrence",
            "recurrence": (
                "COP-derived evaporator load comparison with 1 W hysteresis, mode update "
                "only while setting is enabled, and mode-selected supply setpoint"
            ),
        }
    else:
        raise NiagaraProgramCodegenError(
            f"ProgramObject generator does not support {block.kind.value}"
        )
    if outputs is None:
        outputs = [("out", output_type)]
    slots = {
        "schema": "bactalk-niagara-program-slots/v1",
        "program_name": block.id,
        "slots": [
            *(
                {
                    "name": name,
                    "type_spec": type_spec,
                    "flags": "sL",
                    "direction": "input",
                }
                for name, type_spec in inputs
            ),
            *(
                {
                    "name": name,
                    "type_spec": type_spec,
                    "flags": "rs",
                    "direction": "output",
                }
                for name, type_spec in outputs
            ),
        ],
    }
    return config, class_name, source, kernel, slots, contract


class NiagaraProgramPackageBuilder:
    """Generate reviewable ProgramObject sources for exact non-stock IR blocks.

    This package deliberately contains source and an independently compilable Java
    kernel, not forged ProgramCode bytecode. Niagara must compile the ProgramObject
    in a licensed Workbench/runtime before BACTalk will treat the target as qualified.
    """

    schema = "bactalk-niagara-program-package/v4"

    def build(
        self,
        graph: ControlGraph,
        *,
        controller_id: str | None = None,
        execute_period_seconds: int = 1,
    ) -> bytes:
        if (
            isinstance(execute_period_seconds, bool)
            or not isinstance(execute_period_seconds, int)
            or not 1 <= execute_period_seconds <= 3600
        ):
            raise NiagaraProgramCodegenError(
                "execute_period_seconds must be an integer from 1 through 3600"
            )
        supported_kinds = {
            BlockKind.PID_WITH_RESET,
            BlockKind.TRIM_AND_RESPOND,
            BlockKind.TRIM_AND_RESPOND_HOLD,
            BlockKind.HYSTERESIS,
            BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
            BlockKind.BOOLEAN_DELAY,
            BlockKind.BOOLEAN_INITIALIZATION,
            BlockKind.BOOLEAN_SET_RESET,
            BlockKind.TIMER,
            BlockKind.TIMER_WITH_RESET,
            BlockKind.TIMER_ACCUMULATING,
            BlockKind.MOVING_AVERAGE,
            BlockKind.BOOLEAN_ASSERT_WARNING,
            BlockKind.BOOLEAN_FALLING_EDGE,
            BlockKind.BOOLEAN_PRE_HOST_TICK,
            BlockKind.NUMERIC_SAMPLER,
            BlockKind.NUMERIC_LATCH,
            BlockKind.NUMERIC_UNIT_DELAY,
            BlockKind.NUMERIC_CHANGED,
            BlockKind.PLANT_EQUIPMENT_AVAILABILITY,
            BlockKind.PLANT_ENABLE,
            BlockKind.PLANT_STAGE_COMPLETION,
            BlockKind.PLANT_STAGE_INDEX,
            BlockKind.PLANT_HRC_ENABLE,
            BlockKind.PLANT_HRC_MODE_CONTROL,
        }
        programs = [block for block in graph.blocks if block.kind in supported_kinds]
        if not programs:
            raise NiagaraProgramCodegenError(
                "graph contains no supported non-stock block requiring a ProgramObject"
            )

        entries: dict[str, bytes] = {}
        program_records: list[dict[str, Any]] = []
        for block in programs:
            digest = hashlib.sha256(
                canonical_json(
                    {"id": block.id, "kind": block.kind, "config": block.config}
                ).encode()
            ).hexdigest()
            config, class_name, source, kernel, slots, contract = _program_assets(
                block, execute_period_seconds, digest
            )
            directory = PurePosixPath("programs") / block.id
            program_source = source.encode()
            kernel_source = kernel.encode()
            paths = {
                "program_source": (directory / "ProgramObject.java").as_posix(),
                "standalone_kernel": (directory / f"{class_name}.java").as_posix(),
                "slots": (directory / "slots.json").as_posix(),
            }
            entries[paths["program_source"]] = program_source
            entries[paths["standalone_kernel"]] = kernel_source
            entries[paths["slots"]] = json.dumps(slots, indent=2, sort_keys=True).encode()
            program_records.append(
                {
                    "block_id": block.id,
                    "behavior_kind": block.kind.value,
                    "config": config,
                    "class_name": class_name,
                    "source_contract": contract,
                    "paths": paths,
                    "program_source_sha256": hashlib.sha256(program_source).hexdigest(),
                    "standalone_kernel_sha256": hashlib.sha256(kernel_source).hexdigest(),
                }
            )

        program_ids = {record["block_id"] for record in program_records}
        implementations = {
            block.id: (
                "generated_program_object"
                if block.id in program_ids
                else "qualified_stock_or_boundary"
            )
            for block in graph.blocks
        }
        graph_document = graph.model_dump(mode="json")
        wiring_plan = {
            "schema": "bactalk-niagara-program-wiring/v1",
            "graph_name": graph.name,
            "component_count": len(graph.blocks),
            "link_count": len(graph.links),
            "generated_program_count": len(program_records),
            "components": [
                {
                    "block_id": block.id,
                    "behavior_kind": block.kind.value,
                    "label": block.label,
                    "implementation": implementations[block.id],
                }
                for block in graph.blocks
            ],
            "links": [
                {
                    "source": {
                        "block_id": link.source,
                        "slot": link.source_slot,
                        "implementation": implementations[link.source],
                    },
                    "target": {
                        "block_id": link.target,
                        "slot": link.target_slot,
                        "implementation": implementations[link.target],
                    },
                }
                for link in graph.links
            ],
            "boundary_inputs": [
                block.id
                for block in graph.blocks
                if block.kind in {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}
            ],
            "boundary_outputs": [
                block.id
                for block in graph.blocks
                if block.kind in {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}
            ],
            "licensed_workbench_realization_required": True,
        }
        entries["control-graph.json"] = json.dumps(
            graph_document, indent=2, sort_keys=True
        ).encode()
        entries["wiring-plan.json"] = json.dumps(wiring_plan, indent=2, sort_keys=True).encode()

        readme = (
            b"BACTalk exact Niagara ProgramObject build package\n\n"
            b"1. Review manifest.json, slots.json, and ProgramObject.java.\n"
            b"2. Review control-graph.json and wiring-plan.json for complete topology.\n"
            b"3. Create/import each Niagara ProgramObject with the declared slots.\n"
            b"4. Compile and wire it in the exact licensed Workbench/runtime version.\n"
            b"5. Export the compiled .bog/module and run BACTalk trajectory parity tests.\n"
            b"6. Human approval is still required before any live deployment.\n\n"
            b"The standalone Java kernel has no Niagara dependencies and exists for deterministic "
            b"parity testing. This package is source, not a runtime-qualified Niagara binary.\n"
        )
        entries["README.txt"] = readme
        manifest = {
            "schema": self.schema,
            "controller_id": controller_id,
            "graph_name": graph.name,
            "graph_sha256": hashlib.sha256(canonical_json(graph).encode()).hexdigest(),
            "execute_period_seconds": execute_period_seconds,
            "programs": program_records,
            "control_graph_path": "control-graph.json",
            "wiring_plan_path": "wiring-plan.json",
            "source_contracts": [record["source_contract"] for record in program_records],
            "licensed_workbench_compile_required": True,
            "runtime_qualified": False,
            "live_deployment_allowed": False,
        }
        entries["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True).encode()

        target = io.BytesIO()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, entries[name])
        return target.getvalue()
