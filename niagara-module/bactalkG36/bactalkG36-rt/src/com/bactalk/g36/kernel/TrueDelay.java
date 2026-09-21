package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Logical.TrueDelay} kernel.
 *
 * <p>The output follows a true input after {@code delaySeconds}; a false input
 * clears it at once. With {@code delayOnInit} false an input that is already true
 * on the first step passes through immediately, which is what the stock
 * kitControl:BooleanDelay cannot do (docs/niagara-lowering-matrix.md).
 */
public final class TrueDelay {
  private final double delaySeconds;
  private final boolean delayOnInit;

  private boolean initialized = false;
  private boolean previousInput = false;
  private boolean held = false;
  private double timer = 0.0;
  private double previousTimeSeconds = Double.NaN;

  public TrueDelay(double delaySeconds, boolean delayOnInit) {
    if (delaySeconds < 0.0) {
      throw new IllegalArgumentException("TrueDelay delay must be non-negative");
    }
    this.delaySeconds = delaySeconds;
    this.delayOnInit = delayOnInit;
  }

  public void reset() {
    initialized = false;
    previousInput = false;
    held = false;
    timer = 0.0;
    previousTimeSeconds = Double.NaN;
  }

  public boolean step(double timeSeconds, boolean input) {
    if (!Double.isFinite(timeSeconds)) {
      throw new IllegalArgumentException("TrueDelay time must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("TrueDelay time must be monotonic");
    }
    boolean output;
    double nextTimer;
    if (!input) {
      output = false;
      nextTimer = 0.0;
    } else if (!initialized) {
      if (delayOnInit && delaySeconds > 0.0) {
        output = false;
        nextTimer = 0.0;
      } else {
        output = true;
        nextTimer = delaySeconds;
      }
    } else if (held) {
      output = true;
      nextTimer = delaySeconds;
    } else if (!previousInput) {
      output = delaySeconds <= 0.0;
      nextTimer = 0.0;
    } else {
      nextTimer = timer + timeSeconds - previousTimeSeconds;
      output = nextTimer >= delaySeconds;
    }
    initialized = true;
    previousInput = input;
    held = output;
    timer = nextTimer;
    previousTimeSeconds = timeSeconds;
    return output;
  }
}
