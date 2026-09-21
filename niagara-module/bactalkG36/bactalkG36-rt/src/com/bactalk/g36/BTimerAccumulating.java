package com.bactalk.g36;

import com.bactalk.g36.kernel.TimerAccumulating;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Logical.TimerAccumulating: accumulates true time; a rising reset clears it. */
public final class BTimerAccumulating extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property reset = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property elapsed =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  public static final Property passed =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  public static final Property threshold = newProperty(0, BRelTime.makeSeconds(0), null);

  public static final Type TYPE = Sys.loadType(BTimerAccumulating.class);

  private TimerAccumulating kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusBoolean getIn() {
    return (BStatusBoolean) get(in);
  }

  public BStatusBoolean getReset() {
    return (BStatusBoolean) get(reset);
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
    kernel = new TimerAccumulating(seconds(getThreshold()));
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in || property == reset;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == threshold;
  }

  @Override
  protected boolean inputsValid() {
    return valid(getIn()) && valid(getReset());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getElapsed());
    markNull(getPassed());
  }

  @Override
  protected void step(double timeSeconds) {
    kernel.step(timeSeconds, getIn().getValue(), getReset().getValue());
    getElapsed().setValue(kernel.elapsed());
    getPassed().setValue(kernel.passed());
    markOk(getElapsed());
    markOk(getPassed());
  }
}
