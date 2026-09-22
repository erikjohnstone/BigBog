package com.bactalk.g36;

import com.bactalk.g36.kernel.Hysteresis;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BBoolean;
import javax.baja.sys.BDouble;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Reals.Hysteresis with host-tick semantics: on above uHigh, off below uLow. */
public final class BHysteresis extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  public static final Property uLow = newProperty(0, BDouble.make(0.0), null);
  public static final Property uHigh = newProperty(0, BDouble.make(1.0), null);
  public static final Property initialValue = newProperty(0, BBoolean.FALSE, null);

  public static final Type TYPE = Sys.loadType(BHysteresis.class);

  private Hysteresis kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusNumeric getIn() {
    return (BStatusNumeric) get(in);
  }

  public BStatusBoolean getOut() {
    return (BStatusBoolean) get(out);
  }

  public BDouble getULow() {
    return (BDouble) get(uLow);
  }

  public BDouble getUHigh() {
    return (BDouble) get(uHigh);
  }

  public BBoolean getInitialValue() {
    return (BBoolean) get(initialValue);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new Hysteresis(getULow().getDouble(), getUHigh().getDouble(), getInitialValue().getBoolean());
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == uLow || property == uHigh || property == initialValue;
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
    output.setValue(kernel.step(getIn().getValue()));
    markOk(output);
  }
}
