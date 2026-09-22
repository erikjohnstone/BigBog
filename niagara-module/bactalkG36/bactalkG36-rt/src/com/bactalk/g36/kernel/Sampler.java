package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Discrete.Sampler} kernel: the input held
 * from one sample instant to the next, instants aligned to multiples of the period from
 * time zero. Several executions at one sample instant sample the last input seen there.
 */
public final class Sampler {
  private final double samplePeriodSeconds;

  private boolean initialized = false;
  private double held = 0.0;
  private double t0 = 0.0;
  private long lastIndex = 0L;
  private double previousTimeSeconds = Double.NaN;

  public Sampler(double samplePeriodSeconds) {
    if (!(samplePeriodSeconds > 0.0)) {
      throw new IllegalArgumentException("Sampler period must be positive");
    }
    this.samplePeriodSeconds = samplePeriodSeconds;
  }

  public void reset() {
    initialized = false;
    held = 0.0;
    t0 = 0.0;
    lastIndex = 0L;
    previousTimeSeconds = Double.NaN;
  }

  public double step(double timeSeconds, double input) {
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(input)) {
      throw new IllegalArgumentException("Sampler inputs must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("Sampler time must be monotonic");
    }
    if (!initialized) {
      t0 = Math.floor(timeSeconds / samplePeriodSeconds) * samplePeriodSeconds;
      lastIndex = (long) Math.floor((timeSeconds - t0) / samplePeriodSeconds + 1.0e-9);
      held = input;
      initialized = true;
    } else {
      long index = (long) Math.floor((timeSeconds - t0) / samplePeriodSeconds + 1.0e-9);
      if (index > lastIndex) {
        lastIndex = index;
        held = input;
      } else if (Math.abs(timeSeconds - (t0 + lastIndex * samplePeriodSeconds)) <= 1.0e-9) {
        held = input; // still at the sample instant: the last input wins
      }
    }
    previousTimeSeconds = timeSeconds;
    return held;
  }
}
