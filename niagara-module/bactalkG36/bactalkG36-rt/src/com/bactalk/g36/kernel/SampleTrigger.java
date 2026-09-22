package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Logical.Sources.SampleTrigger} kernel: true for
 * the execution at which a new period boundary (period, shifted by shift) has been passed.
 */
public final class SampleTrigger {
  private final double periodSeconds;
  private final double phaseSeconds;

  private long lastIndex = -1L;
  private double previousTimeSeconds = Double.NaN;

  public SampleTrigger(double periodSeconds, double shiftSeconds) {
    if (!(periodSeconds > 0.0)) {
      throw new IllegalArgumentException("SampleTrigger period must be positive");
    }
    this.periodSeconds = periodSeconds;
    this.phaseSeconds = shiftSeconds - Math.floor(shiftSeconds / periodSeconds) * periodSeconds;
  }

  public void reset() {
    lastIndex = -1L;
    previousTimeSeconds = Double.NaN;
  }

  public boolean step(double timeSeconds) {
    if (!Double.isFinite(timeSeconds)) {
      throw new IllegalArgumentException("SampleTrigger time must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("SampleTrigger time must be monotonic");
    }
    long index = (long) Math.floor((timeSeconds - phaseSeconds) / periodSeconds + 1.0e-9);
    boolean fired = index > lastIndex;
    if (fired) {
      lastIndex = index;
    }
    previousTimeSeconds = timeSeconds;
    return fired;
  }
}
