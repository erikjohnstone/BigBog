package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Logical.TrueFalseHold} kernel: the
 * output holds each state for at least its configured duration before following
 * the input.
 */
public final class TrueFalseHold {
  private final double trueHoldSeconds;
  private final double falseHoldSeconds;

  private boolean initialized = false;
  private boolean held = false;
  private double elapsed = 0.0;
  private double previousTimeSeconds = Double.NaN;

  public TrueFalseHold(double trueHoldSeconds, double falseHoldSeconds) {
    this.trueHoldSeconds = trueHoldSeconds;
    this.falseHoldSeconds = falseHoldSeconds;
  }

  public void reset() {
    initialized = false;
    held = false;
    elapsed = 0.0;
    previousTimeSeconds = Double.NaN;
  }

  public boolean step(double timeSeconds, boolean input) {
    if (!Double.isFinite(timeSeconds)) {
      throw new IllegalArgumentException("TrueFalseHold time must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("TrueFalseHold time must be monotonic");
    }
    if (!initialized) {
      initialized = true;
      held = input;
      elapsed = 0.0;
      previousTimeSeconds = timeSeconds;
      return held;
    }
    elapsed += timeSeconds - previousTimeSeconds;
    previousTimeSeconds = timeSeconds;
    if (input != held) {
      double required = Math.max(0.0, held ? trueHoldSeconds : falseHoldSeconds);
      if (elapsed >= required) {
        held = input;
        elapsed = 0.0;
      }
    }
    return held;
  }
}
