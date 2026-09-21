package com.bactalk.g36;

import com.bactalk.g36.kernel.TrueDelay;
import javax.baja.status.BStatusBoolean;
import javax.baja.sys.BBoolean;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Logical.TrueDelay: out follows a true in after delayTime; false clears at once. */
public final class BTrueDelay extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  public static final Property delayTime = newProperty(0, BRelTime.makeSeconds(0), null);
  public static final Property delayOnInit = newProperty(0, BBoolean.FALSE, null);

  public static final Type TYPE = Sys.loadType(BTrueDelay.class);

  private TrueDelay kernel;

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

  public BRelTime getDelayTime() {
    return (BRelTime) get(delayTime);
  }

  public BBoolean getDelayOnInit() {
    return (BBoolean) get(delayOnInit);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new TrueDelay(seconds(getDelayTime()), getDelayOnInit().getBoolean());
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == delayTime || property == delayOnInit;
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
