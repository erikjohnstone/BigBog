package com.bactalk.g36;

import com.bactalk.g36.kernel.TrueFalseHold;
import javax.baja.status.BStatusBoolean;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Logical.TrueFalseHold: each output state is held for at least its duration. */
public final class BTrueFalseHold extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  public static final Property trueHoldTime = newProperty(0, BRelTime.makeSeconds(0), null);
  public static final Property falseHoldTime = newProperty(0, BRelTime.makeSeconds(0), null);

  public static final Type TYPE = Sys.loadType(BTrueFalseHold.class);

  private TrueFalseHold kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusBoolean getIn() {
    return (BStatusBoolean) get(in);
  }

  public BStatusBoolean getOut() {
    return (BStatusBoolean) get(out);
  }

  public BRelTime getTrueHoldTime() {
    return (BRelTime) get(trueHoldTime);
  }

  public BRelTime getFalseHoldTime() {
    return (BRelTime) get(falseHoldTime);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new TrueFalseHold(seconds(getTrueHoldTime()), seconds(getFalseHoldTime()));
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == trueHoldTime || property == falseHoldTime;
  }

  @Override
  protected boolean inputsValid() {
    return valid(getIn());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusBoolean output = getOut();
    output.setValue(kernel.step(timeSeconds, getIn().getValue()));
    markOk(output);
  }
}
