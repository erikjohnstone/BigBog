package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Discrete.UnitDelay} kernel: the
 * output is the input sampled one period earlier, with sample instants aligned to
 * multiples of the period from time zero. Several steps at one sample instant
 * (event-driven executions) sample the last input seen at that instant.
 */
public final class UnitDelay {
  private final double samplePeriodSeconds;
  private final double initial;

  private boolean initialized = false;
  private double held;
  private double staged;
  private double t0 = 0.0;
  private long lastIndex = 0L;
  private double previousTimeSeconds = Double.NaN;

  public UnitDelay(double samplePeriodSeconds, double initial) {
    if (!(samplePeriodSeconds > 0.0)) {
      throw new IllegalArgumentException("UnitDelay period must be positive");
    }
    this.samplePeriodSeconds = samplePeriodSeconds;
    this.initial = initial;
    this.held = initial;
    this.staged = initial;
  }

  public void reset() {
    initialized = false;
    held = initial;
    staged = initial;
    t0 = 0.0;
    lastIndex = 0L;
    previousTimeSeconds = Double.NaN;
  }

  public double step(double timeSeconds, double input) {
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(input)) {
      throw new IllegalArgumentException("UnitDelay inputs must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("UnitDelay time must be monotonic");
    }
    if (!initialized) {
      t0 = Math.floor(timeSeconds / samplePeriodSeconds) * samplePeriodSeconds;
      lastIndex = (long) Math.floor((timeSeconds - t0) / samplePeriodSeconds + 1.0e-9);
      double boundary = t0 + lastIndex * samplePeriodSeconds;
      staged = Math.abs(timeSeconds - boundary) <= 1.0e-9 ? input : initial;
      initialized = true;
      previousTimeSeconds = timeSeconds;
      return initial;
    }
    long index = (long) Math.floor((timeSeconds - t0) / samplePeriodSeconds + 1.0e-9);
    if (index > lastIndex) {
      held = staged;
      staged = input;
      lastIndex = index;
    } else if (Math.abs(timeSeconds - (t0 + lastIndex * samplePeriodSeconds)) <= 1.0e-9) {
      // Still at the sample instant: the value sampled is the last one seen there,
      // as a CDL solver samples after its event iteration settles.
      staged = input;
    }
    previousTimeSeconds = timeSeconds;
    return held;
  }
}
