package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Reals.Hysteresis} kernel: the output switches
 * on when the input rises above uHigh and off when it falls below uLow, with host-tick
 * semantics so a transient value inside one link propagation cannot latch it.
 */
public final class Hysteresis {
  private final double uLow;
  private final double uHigh;
  private final boolean initial;
  private boolean output;

  public Hysteresis(double uLow, double uHigh, boolean initial) {
    if (!(uHigh > uLow)) {
      throw new IllegalArgumentException("Hysteresis needs uHigh > uLow");
    }
    this.uLow = uLow;
    this.uHigh = uHigh;
    this.initial = initial;
    this.output = initial;
  }

  public void reset() {
    output = initial;
  }

  public boolean step(double input) {
    if (!Double.isFinite(input)) {
      throw new IllegalArgumentException("Hysteresis input must be finite");
    }
    output = (!output && input > uHigh) || (output && input >= uLow);
    return output;
  }
}
