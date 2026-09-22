package com.bactalk.g36;

import com.bactalk.g36.kernel.LimitSlewRate;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BBoolean;
import javax.baja.sys.BDouble;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Reals.LimitSlewRate: the input followed at no more than the configured rates. */
public final class BLimitSlewRate extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  public static final Property raisingSlewRate = newProperty(0, BDouble.make(1.0), null);
  public static final Property fallingSlewRate = newProperty(0, BDouble.make(-1.0), null);
  public static final Property derivativeTime = newProperty(0, BRelTime.makeSeconds(10), null);
  public static final Property enable = newProperty(0, BBoolean.TRUE, null);

  public static final Type TYPE = Sys.loadType(BLimitSlewRate.class);

  private LimitSlewRate kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusNumeric getIn() {
    return (BStatusNumeric) get(in);
  }

  public BStatusNumeric getOut() {
    return (BStatusNumeric) get(out);
  }

  public BDouble getRaisingSlewRate() {
    return (BDouble) get(raisingSlewRate);
  }

  public BDouble getFallingSlewRate() {
    return (BDouble) get(fallingSlewRate);
  }

  public BRelTime getDerivativeTime() {
    return (BRelTime) get(derivativeTime);
  }

  public BBoolean getEnable() {
    return (BBoolean) get(enable);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new LimitSlewRate(
        getRaisingSlewRate().getDouble(),
        getFallingSlewRate().getDouble(),
        seconds(getDerivativeTime()),
        getEnable().getBoolean());
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == raisingSlewRate
        || property == fallingSlewRate
        || property == derivativeTime
        || property == enable;
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
    BStatusNumeric output = getOut();
    output.setValue(kernel.step(timeSeconds, getIn().getValue()));
    markOk(output);
  }
}
