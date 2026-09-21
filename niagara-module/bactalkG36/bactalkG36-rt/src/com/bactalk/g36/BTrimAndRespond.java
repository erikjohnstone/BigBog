package com.bactalk.g36;

import com.bactalk.g36.kernel.TrimAndRespond;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BBoolean;
import javax.baja.sys.BDouble;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** G36 Generic.TrimAndRespond, with the optional hold input (holdEnabled). */
public final class BTrimAndRespond extends BKernelComponent {
  public static final Property requestCount =
      newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property deviceOn = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  /** Read only when holdEnabled is true. */
  public static final Property hold = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  public static final Property initialSetpoint = newProperty(0, BDouble.make(0.0), null);
  public static final Property minimumSetpoint = newProperty(0, BDouble.make(0.0), null);
  public static final Property maximumSetpoint = newProperty(0, BDouble.make(0.0), null);
  public static final Property delayTime = newProperty(0, BRelTime.makeSeconds(0), null);
  public static final Property samplePeriod = newProperty(0, BRelTime.makeSeconds(120), null);
  public static final Property ignoredRequests = newProperty(0, BDouble.make(0.0), null);
  public static final Property trimAmount = newProperty(0, BDouble.make(0.0), null);
  public static final Property respondAmount = newProperty(0, BDouble.make(0.0), null);
  public static final Property maximumResponse = newProperty(0, BDouble.make(0.0), null);
  public static final Property holdEnabled = newProperty(0, BBoolean.FALSE, null);
  public static final Property holdDuration = newProperty(0, BRelTime.makeSeconds(0), null);

  public static final Type TYPE = Sys.loadType(BTrimAndRespond.class);

  private TrimAndRespond kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusNumeric getRequestCount() {
    return (BStatusNumeric) get(requestCount);
  }

  public BStatusBoolean getDeviceOn() {
    return (BStatusBoolean) get(deviceOn);
  }

  public BStatusBoolean getHold() {
    return (BStatusBoolean) get(hold);
  }

  public BStatusNumeric getOut() {
    return (BStatusNumeric) get(out);
  }

  private double number(Property property) {
    return ((BDouble) get(property)).getDouble();
  }

  private boolean holdInUse() {
    return ((BBoolean) get(holdEnabled)).getBoolean();
  }

  @Override
  protected void rebuildKernel() {
    kernel = new TrimAndRespond(
        number(initialSetpoint),
        number(minimumSetpoint),
        number(maximumSetpoint),
        seconds((BRelTime) get(delayTime)),
        seconds((BRelTime) get(samplePeriod)),
        number(ignoredRequests),
        number(trimAmount),
        number(respondAmount),
        number(maximumResponse),
        holdInUse(),
        seconds((BRelTime) get(holdDuration)));
  }

  @Override
  protected boolean isInput(Property property) {
    return property == requestCount || property == deviceOn || property == hold;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == initialSetpoint
        || property == minimumSetpoint
        || property == maximumSetpoint
        || property == delayTime
        || property == samplePeriod
        || property == ignoredRequests
        || property == trimAmount
        || property == respondAmount
        || property == maximumResponse
        || property == holdEnabled
        || property == holdDuration;
  }

  @Override
  protected boolean inputsValid() {
    return valid(getRequestCount()) && valid(getDeviceOn()) && (!holdInUse() || valid(getHold()));
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusNumeric output = getOut();
    double value = holdInUse()
        ? kernel.step(
            timeSeconds, getRequestCount().getValue(), getDeviceOn().getValue(), getHold().getValue())
        : kernel.step(timeSeconds, getRequestCount().getValue(), getDeviceOn().getValue());
    output.setValue(value);
    markOk(output);
  }
}
