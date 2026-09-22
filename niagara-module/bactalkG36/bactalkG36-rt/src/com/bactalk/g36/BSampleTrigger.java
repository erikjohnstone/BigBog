package com.bactalk.g36;

import com.bactalk.g36.kernel.SampleTrigger;
import javax.baja.status.BStatusBoolean;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Logical.Sources.SampleTrigger: true for one execution at each period boundary. */
public final class BSampleTrigger extends BKernelComponent {
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  public static final Property period = newProperty(0, BRelTime.makeSeconds(1), null);
  public static final Property shift = newProperty(0, BRelTime.makeSeconds(0), null);

  public static final Type TYPE = Sys.loadType(BSampleTrigger.class);

  private SampleTrigger kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusBoolean getOut() {
    return (BStatusBoolean) get(out);
  }

  public BRelTime getPeriod() {
    return (BRelTime) get(period);
  }

  public BRelTime getShift() {
    return (BRelTime) get(shift);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new SampleTrigger(seconds(getPeriod()), seconds(getShift()));
  }

  @Override
  protected boolean isInput(Property property) {
    return false;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == period || property == shift;
  }


  @Override
  protected boolean inputsValid() {
    return true;
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusBoolean output = getOut();
    output.setValue(kernel.step(timeSeconds));
    markOk(output);
  }
}
