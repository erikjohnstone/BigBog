package com.bactalk.g36;

import com.bactalk.g36.kernel.Pre;
import javax.baja.status.BStatusBoolean;
import javax.baja.sys.BBoolean;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Logical.Pre (host_tick_v1): out is the in of the previous execution. */
public final class BPre extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusBoolean(false), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  public static final Property initialValue = newProperty(0, BBoolean.FALSE, null);

  public static final Type TYPE = Sys.loadType(BPre.class);

  private Pre kernel;

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

  public BBoolean getInitialValue() {
    return (BBoolean) get(initialValue);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new Pre(getInitialValue().getBoolean());
  }

  @Override
  protected boolean isInput(Property property) {
    // A Pre advances only on the execution tick, never on an input change:
    // that is what makes it a one-tick delay rather than a pass-through.
    return false;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == initialValue;
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
