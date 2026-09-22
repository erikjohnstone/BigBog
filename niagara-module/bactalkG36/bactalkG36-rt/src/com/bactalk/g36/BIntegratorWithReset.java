package com.bactalk.g36;

import com.bactalk.g36.kernel.IntegratorWithReset;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BDouble;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Reals.IntegratorWithReset: out integrates gain * in; a rising trigger loads resetValue. */
public final class BIntegratorWithReset extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property resetValue =
      newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property trigger =
      newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  public static final Property gain = newProperty(0, BDouble.make(1.0), null);
  public static final Property initialValue = newProperty(0, BDouble.make(0.0), null);

  public static final Type TYPE = Sys.loadType(BIntegratorWithReset.class);

  private IntegratorWithReset kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusNumeric getIn() {
    return (BStatusNumeric) get(in);
  }

  public BStatusNumeric getResetValue() {
    return (BStatusNumeric) get(resetValue);
  }

  public BStatusBoolean getTrigger() {
    return (BStatusBoolean) get(trigger);
  }

  public BStatusNumeric getOut() {
    return (BStatusNumeric) get(out);
  }

  public BDouble getGain() {
    return (BDouble) get(gain);
  }

  public BDouble getInitialValue() {
    return (BDouble) get(initialValue);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new IntegratorWithReset(getGain().getDouble(), getInitialValue().getDouble());
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in || property == resetValue || property == trigger;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == gain || property == initialValue;
  }

  @Override
  protected boolean resamplesAtInstantEnd() {
    return true; // the step at a tick takes the settled inputs of the instant
  }

  @Override
  protected boolean inputsValid() {
    return valid(getIn()) && valid(getResetValue()) && valid(getTrigger());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusNumeric output = getOut();
    output.setValue(
        kernel.step(
            timeSeconds,
            getIn().getValue(),
            getResetValue().getValue(),
            getTrigger().getValue()));
    markOk(output);
  }
}
