package com.bactalk.g36;

import com.bactalk.g36.kernel.OnCounter;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BDouble;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Integers.OnCounter: out counts rising triggers; a rising reset returns it to start. */
public final class BOnCounter extends BKernelComponent {
  public static final Property trigger =
      newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property reset = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  public static final Property initialValue = newProperty(0, BDouble.make(0.0), null);

  public static final Type TYPE = Sys.loadType(BOnCounter.class);

  private OnCounter kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusBoolean getTrigger() {
    return (BStatusBoolean) get(trigger);
  }

  public BStatusBoolean getReset() {
    return (BStatusBoolean) get(reset);
  }

  public BStatusNumeric getOut() {
    return (BStatusNumeric) get(out);
  }

  public BDouble getInitialValue() {
    return (BDouble) get(initialValue);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new OnCounter(getInitialValue().getDouble());
  }

  @Override
  protected boolean isInput(Property property) {
    return property == trigger || property == reset;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == initialValue;
  }

  @Override
  protected boolean resamplesAtInstantEnd() {
    return true; // the step at a tick takes the settled inputs of the instant
  }

  @Override
  protected boolean inputsValid() {
    return valid(getTrigger()) && valid(getReset());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusNumeric output = getOut();
    output.setValue(kernel.step(timeSeconds, getTrigger().getValue(), getReset().getValue()));
    markOk(output);
  }
}
