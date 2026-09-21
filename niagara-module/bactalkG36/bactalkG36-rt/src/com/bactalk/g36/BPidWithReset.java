package com.bactalk.g36;

import com.bactalk.g36.kernel.PidWithReset;
import java.util.Locale;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BBoolean;
import javax.baja.sys.BDouble;
import javax.baja.sys.BString;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Reals.PIDWithReset: the CDL-exact loop with a rising-edge reset trigger. */
public final class BPidWithReset extends BKernelComponent {
  public static final Property setpoint = newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property measurement =
      newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property trigger = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  /** One of P, PI, PD, PID. */
  public static final Property controllerType = newProperty(0, BString.make("PI"), null);
  public static final Property reverseActing = newProperty(0, BBoolean.FALSE, null);
  public static final Property k = newProperty(0, BDouble.make(1.0), null);
  public static final Property ti = newProperty(0, BDouble.make(0.5), null);
  public static final Property td = newProperty(0, BDouble.make(0.1), null);
  public static final Property r = newProperty(0, BDouble.make(1.0), null);
  public static final Property ni = newProperty(0, BDouble.make(0.9), null);
  public static final Property nd = newProperty(0, BDouble.make(10.0), null);
  public static final Property yMin = newProperty(0, BDouble.make(0.0), null);
  public static final Property yMax = newProperty(0, BDouble.make(1.0), null);
  public static final Property xiStart = newProperty(0, BDouble.make(0.0), null);
  public static final Property ydStart = newProperty(0, BDouble.make(0.0), null);
  public static final Property yReset = newProperty(0, BDouble.make(0.0), null);

  public static final Type TYPE = Sys.loadType(BPidWithReset.class);

  private PidWithReset kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusNumeric getSetpoint() {
    return (BStatusNumeric) get(setpoint);
  }

  public BStatusNumeric getMeasurement() {
    return (BStatusNumeric) get(measurement);
  }

  public BStatusBoolean getTrigger() {
    return (BStatusBoolean) get(trigger);
  }

  public BStatusNumeric getOut() {
    return (BStatusNumeric) get(out);
  }

  private double number(Property property) {
    return ((BDouble) get(property)).getDouble();
  }

  @Override
  protected void rebuildKernel() {
    String type = ((BString) get(controllerType)).getString().trim().toUpperCase(Locale.ROOT);
    kernel = new PidWithReset(
        PidWithReset.ControllerType.valueOf(type),
        ((BBoolean) get(reverseActing)).getBoolean(),
        number(k),
        number(ti),
        number(td),
        number(r),
        number(ni),
        number(nd),
        number(yMin),
        number(yMax),
        number(xiStart),
        number(ydStart),
        number(yReset));
  }

  @Override
  protected boolean isInput(Property property) {
    return property == setpoint || property == measurement || property == trigger;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == controllerType
        || property == reverseActing
        || property == k
        || property == ti
        || property == td
        || property == r
        || property == ni
        || property == nd
        || property == yMin
        || property == yMax
        || property == xiStart
        || property == ydStart
        || property == yReset;
  }

  @Override
  protected boolean inputsValid() {
    return valid(getSetpoint()) && valid(getMeasurement()) && valid(getTrigger());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusNumeric output = getOut();
    output.setValue(kernel.step(
        timeSeconds,
        getSetpoint().getValue(),
        getMeasurement().getValue(),
        getTrigger().getValue()));
    markOk(output);
  }
}
