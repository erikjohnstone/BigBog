package com.bactalk.g36;

import com.bactalk.g36.kernel.Timer;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Logical.Timer: elapsed seconds while in is true and passed once past threshold. */
public final class BTimer extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property elapsed =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  public static final Property passed =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  public static final Property threshold = newProperty(0, BRelTime.makeSeconds(0), null);

  public static final Type TYPE = Sys.loadType(BTimer.class);

  private Timer kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusBoolean getIn() {
    return (BStatusBoolean) get(in);
  }

  public BStatusNumeric getElapsed() {
    return (BStatusNumeric) get(elapsed);
  }

  public BStatusBoolean getPassed() {
    return (BStatusBoolean) get(passed);
  }

  public BRelTime getThreshold() {
    return (BRelTime) get(threshold);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new Timer(seconds(getThreshold()));
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == threshold;
  }

  @Override
  protected boolean inputsValid() {
    return valid(getIn());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getElapsed());
    markNull(getPassed());
  }

  @Override
  protected void step(double timeSeconds) {
    kernel.step(timeSeconds, getIn().getValue());
    getElapsed().setValue(kernel.elapsed());
    getPassed().setValue(kernel.passed());
    markOk(getElapsed());
    markOk(getPassed());
  }
}
