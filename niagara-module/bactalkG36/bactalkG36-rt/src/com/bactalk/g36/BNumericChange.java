package com.bactalk.g36;

import com.bactalk.g36.kernel.NumericChange;
import java.util.Locale;
import javax.baja.status.BStatusBoolean;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BDouble;
import javax.baja.sys.BString;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** Change detector: out is true on the execution where in changed in the chosen direction. */
public final class BNumericChange extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusBoolean(false), null);
  /** One of changed, increased, decreased. */
  public static final Property mode = newProperty(0, BString.make("changed"), null);
  public static final Property initialValue = newProperty(0, BDouble.make(0.0), null);

  public static final Type TYPE = Sys.loadType(BNumericChange.class);

  private NumericChange kernel;

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

  @Override
  protected void rebuildKernel() {
    String selected = ((BString) get(mode)).getString().trim().toUpperCase(Locale.ROOT);
    kernel = new NumericChange(
        NumericChange.Mode.valueOf(selected), ((BDouble) get(initialValue)).getDouble());
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == mode || property == initialValue;
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
