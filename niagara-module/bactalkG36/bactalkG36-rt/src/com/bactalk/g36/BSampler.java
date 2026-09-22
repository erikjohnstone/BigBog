package com.bactalk.g36;

import com.bactalk.g36.kernel.Sampler;
import javax.baja.status.BStatusNumeric;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CDL.Discrete.Sampler: the input held from one period-aligned sample instant to the next. */
public final class BSampler extends BKernelComponent {
  public static final Property in = newProperty(Flags.SUMMARY, new BStatusNumeric(0.0), null);
  public static final Property out =
      newProperty(Flags.SUMMARY | Flags.READONLY | Flags.TRANSIENT, new BStatusNumeric(0.0), null);
  public static final Property samplePeriod = newProperty(0, BRelTime.makeSeconds(1), null);

  public static final Type TYPE = Sys.loadType(BSampler.class);

  private Sampler kernel;

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

  public BRelTime getSamplePeriod() {
    return (BRelTime) get(samplePeriod);
  }

  @Override
  protected void rebuildKernel() {
    kernel = new Sampler(seconds(getSamplePeriod()));
  }

  @Override
  protected boolean isInput(Property property) {
    return property == in;
  }

  @Override
  protected boolean isParameter(Property property) {
    return property == samplePeriod;
  }


  @Override
  protected boolean resamplesAtInstantEnd() {
    return true; // samples at period boundaries take the settled value of the instant
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
