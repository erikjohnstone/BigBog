package com.bactalk.g36.kernel;

/**
 * CDL.Reals.IntegratorWithReset as the reference engine discretises it: an execution
 * returns the state the previous instant left, then takes a forward-Euler step of
 * gain * input over the time since the previous instant (none on the first) or jumps to
 * the reset value on a rising trigger. A second execution at the same instant recomputes
 * that step from the instant's settled inputs, so a resample never integrates twice.
 */
public final class IntegratorWithReset {
  private final double gain;
  private final double initial;
  private double state;
  private double previousTime;
  private boolean previousTrigger;
  private double instant;
  private double instantState;
  private double instantPreviousTime;
  private boolean instantPreviousTrigger;

  public IntegratorWithReset(double gain, double initial) {
    if (!Double.isFinite(gain) || !Double.isFinite(initial)) {
      throw new IllegalArgumentException("IntegratorWithReset needs finite gain and start");
    }
    this.gain = gain;
    this.initial = initial;
    reset();
  }

  public void reset() {
    state = initial;
    previousTime = Double.NaN;
    previousTrigger = false;
    instant = Double.NaN;
  }

  public double step(double timeSeconds, double input, double resetValue, boolean trigger) {
    if (!(timeSeconds == instant)) {
      instant = timeSeconds;
      instantState = state;
      instantPreviousTime = previousTime;
      instantPreviousTrigger = previousTrigger;
    }
    double dt = Double.isNaN(instantPreviousTime) ? 0.0 : timeSeconds - instantPreviousTime;
    if (trigger && !instantPreviousTrigger) {
      state = resetValue;
    } else {
      state = instantState + gain * input * dt;
    }
    previousTime = timeSeconds;
    previousTrigger = trigger;
    return instantState;
  }
}
