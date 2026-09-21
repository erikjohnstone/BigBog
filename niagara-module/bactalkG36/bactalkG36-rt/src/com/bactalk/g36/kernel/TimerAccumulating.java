package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Logical.TimerAccumulating} kernel:
 * accumulates time while the input is true; a rising edge on {@code reset} clears it.
 */
public final class TimerAccumulating {
  private final double thresholdSeconds;

  private boolean initialized = false;
  private double previousTimeSeconds = Double.NaN;
  private boolean previousInput = false;
  private boolean previousReset = false;
  private double elapsedOutput = 0.0;
  private boolean passedOutput;

  public TimerAccumulating(double thresholdSeconds) {
    this.thresholdSeconds = thresholdSeconds;
    this.passedOutput = thresholdSeconds <= 0.0;
  }

  public void reset() {
    initialized = false;
    previousTimeSeconds = Double.NaN;
    previousInput = false;
    previousReset = false;
    elapsedOutput = 0.0;
    passedOutput = thresholdSeconds <= 0.0;
  }

  public void step(double timeSeconds, boolean input, boolean resetInput) {
    if (!Double.isFinite(timeSeconds)) {
      throw new IllegalArgumentException("TimerAccumulating time must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("TimerAccumulating time must be monotonic");
    }
    if (!initialized) {
      initialized = true;
    } else if (resetInput && !previousReset) {
      elapsedOutput = 0.0;
      passedOutput = thresholdSeconds <= 0.0;
    } else {
      if (previousInput) {
        elapsedOutput += timeSeconds - previousTimeSeconds;
      }
      if (input && elapsedOutput >= thresholdSeconds) {
        passedOutput = true;
      }
    }
    previousTimeSeconds = timeSeconds;
    previousInput = input;
    previousReset = resetInput;
  }

  public double elapsed() {
    return elapsedOutput;
  }

  public boolean passed() {
    return passedOutput;
  }
}
