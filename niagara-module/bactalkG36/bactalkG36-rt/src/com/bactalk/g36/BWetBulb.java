package com.bactalk.g36;

import com.bactalk.g36.kernel.WetBulb;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Psychrometrics.WetBulb_TDryBulPhi: wet-bulb temperature from dry bulb and humidity. */
public final class BWetBulb extends BKernelComponent {
  public static final Property dryBulb = newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property relativeHumidity =
      newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);

  public static final Type TYPE = Sys.loadType(BWetBulb.class);

  private WetBulb kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusNumeric getDryBulb() {
    return (BStatusNumeric) get(dryBulb);
  }

  public BStatusNumeric getRelativeHumidity() {
    return (BStatusNumeric) get(relativeHumidity);
  }

  public BStatusNumeric getOut() {
    return (BStatusNumeric) get(out);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new WetBulb();
  }

  @Override
  protected boolean isInput(Property property) {
    return property == dryBulb || property == relativeHumidity;
  }

  @Override
  protected boolean isParameter(Property property) {
    return false;
  }

  @Override
  protected boolean inputsValid() {
    return valid(getDryBulb()) && valid(getRelativeHumidity());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusNumeric output = getOut();
    output.setValue(
        kernel.step(timeSeconds, getDryBulb().getValue(), getRelativeHumidity().getValue()));
    markOk(output);
  }
}
