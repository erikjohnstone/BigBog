package com.bactalk.g36.kernel;

/**
 * {@code Buildings.Templates.Plants.Controls.Utilities.TimerWithReset} kernel: a
 * rising edge on {@code reset} restarts the timer while the input stays true.
 */
public final class TimerWithReset {
  private final double thresholdSeconds;

  private boolean initialized = false;
  private double entryTimeSeconds = 0.0;
  private double previousTimeSeconds = Double.NaN;
  private boolean previousInput = false;
  private boolean previousReset = false;
  private double elapsedOutput = 0.0;
  private boolean passedOutput = false;

  public TimerWithReset(double thresholdSeconds) {
    this.thresholdSeconds = thresholdSeconds;
  }

  public void reset() {
    initialized = false;
    entryTimeSeconds = 0.0;
    previousTimeSeconds = Double.NaN;
    previousInput = false;
    previousReset = false;
    elapsedOutput = 0.0;
    passedOutput = false;
  }

  public void step(double timeSeconds, boolean input, boolean resetInput) {
    if (!Double.isFinite(timeSeconds)) {
      throw new IllegalArgumentException("TimerWithReset time must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("TimerWithReset time must be monotonic");
    }
    if (!initialized) {
      entryTimeSeconds = timeSeconds;
      elapsedOutput = 0.0;
      passedOutput = input && thresholdSeconds <= 0.0;
      initialized = true;
    } else {
      boolean risingInput = input && !previousInput;
      boolean risingReset = resetInput && !previousReset;
      if (risingInput || risingReset) {
        entryTimeSeconds = timeSeconds;
        passedOutput = input && thresholdSeconds <= 0.0;
      } else if (input && timeSeconds >= entryTimeSeconds + thresholdSeconds) {
        passedOutput = true;
      } else if (!input && previousInput) {
        passedOutput = false;
      }
      elapsedOutput = input ? timeSeconds - entryTimeSeconds : 0.0;
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
