package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Discrete.FirstOrderHold} kernel:
 * linear extrapolation from the last two samples between sample instants.
 */
public final class FirstOrderHold {
  private final double samplePeriodSeconds;

  private boolean initialized = false;
  private double t0 = 0.0;
  private long lastIndex = 0L;
  private double tSample = 0.0;
  private double uSample = 0.0;
  private double preUSample = 0.0;
  private double slope = 0.0;
  private double previousTimeSeconds = Double.NaN;

  public FirstOrderHold(double samplePeriodSeconds) {
    if (!(samplePeriodSeconds > 0.0)) {
      throw new IllegalArgumentException("FirstOrderHold period must be positive");
    }
    this.samplePeriodSeconds = samplePeriodSeconds;
  }

  public void reset() {
    initialized = false;
    t0 = 0.0;
    lastIndex = 0L;
    tSample = 0.0;
    uSample = 0.0;
    preUSample = 0.0;
    slope = 0.0;
    previousTimeSeconds = Double.NaN;
  }

  public double step(double timeSeconds, double input) {
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(input)) {
      throw new IllegalArgumentException("FirstOrderHold inputs must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("FirstOrderHold time must be monotonic");
    }
    if (!initialized) {
      t0 = Math.rint(Math.floor(timeSeconds / samplePeriodSeconds) * samplePeriodSeconds * 1.0e6)
          / 1.0e6;
      lastIndex = (long) Math.floor((timeSeconds - t0) / samplePeriodSeconds + 1.0e-9);
      tSample = t0;
      uSample = input;
      preUSample = input;
      slope = 0.0;
      initialized = true;
      previousTimeSeconds = timeSeconds;
      return input;
    }
    long index = (long) Math.floor((timeSeconds - t0) / samplePeriodSeconds + 1.0e-9);
    boolean due = index > lastIndex;
    double output = due ? uSample : preUSample + slope * (timeSeconds - tSample);
    if (due) {
      double previous = uSample;
      lastIndex = index;
      tSample = timeSeconds;
      uSample = input;
      preUSample = previous;
      slope = timeSeconds <= t0 + samplePeriodSeconds / 2.0
          ? 0.0
          : (input - previous) / samplePeriodSeconds;
    }
    previousTimeSeconds = timeSeconds;
    return output;
  }
}
