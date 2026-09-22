package com.bactalk.g36;

import com.bactalk.g36.kernel.SetReset;
import javax.baja.status.BStatusBoolean;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Logical.Latch with host-tick semantics: set on a rising edge, clear dominant. */
public final class BSetReset extends BKernelComponent {
  public static final Property set = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property clear = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);

  public static final Type TYPE = Sys.loadType(BSetReset.class);

  private SetReset kernel;

  @Override
  public Type getType() {
    return TYPE;
  }

  public BStatusBoolean getSet() {
    return (BStatusBoolean) get(set);
  }

  public BStatusBoolean getClear() {
    return (BStatusBoolean) get(clear);
  }

  public BStatusBoolean getOut() {
    return (BStatusBoolean) get(out);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new SetReset();
  }

  @Override
  protected boolean isInput(Property property) {
    return property == set || property == clear;
  }

  @Override
  protected boolean isParameter(Property property) {
    return false;
  }


  @Override
  protected boolean inputsValid() {
    return valid(getSet()) && valid(getClear());
  }

  @Override
  protected void markOutputsNull() {
    markNull(getOut());
  }

  @Override
  protected void step(double timeSeconds) {
    BStatusBoolean output = getOut();
    output.setValue(kernel.step(getSet().getValue(), getClear().getValue()));
    markOk(output);
  }
}
