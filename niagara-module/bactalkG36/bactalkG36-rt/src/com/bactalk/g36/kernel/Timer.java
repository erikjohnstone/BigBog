package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Logical.Timer} kernel: elapsed time
 * while the input is true and a {@code passed} flag once it exceeds the threshold.
 */
public final class Timer {
  private final double thresholdSeconds;

  private boolean initialized = false;
  private double entryTimeSeconds = 0.0;
  private double previousTimeSeconds = Double.NaN;
  private boolean previousInput = false;
  private boolean passed;
  private double elapsedOutput = 0.0;
  private boolean passedOutput;

  public Timer(double thresholdSeconds) {
    this.thresholdSeconds = thresholdSeconds;
    this.passed = thresholdSeconds <= 0.0;
    this.passedOutput = thresholdSeconds <= 0.0;
  }

  public void reset() {
    initialized = false;
    entryTimeSeconds = 0.0;
    previousTimeSeconds = Double.NaN;
    previousInput = false;
    passed = thresholdSeconds <= 0.0;
    elapsedOutput = 0.0;
    passedOutput = thresholdSeconds <= 0.0;
  }

  public void step(double timeSeconds, boolean input) {
    if (!Double.isFinite(timeSeconds)) {
      throw new IllegalArgumentException("Timer time must be finite");
    }
    if (!Double.isNaN(previousTimeSeconds) && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("Timer time must be monotonic");
    }
    double elapsed;
    if (!input || !initialized || !previousInput) {
      elapsed = 0.0;
    } else {
      elapsed = timeSeconds - entryTimeSeconds;
    }
    boolean nextPassed;
    if (input && !previousInput) {
      nextPassed = thresholdSeconds <= 0.0;
    } else if (input && elapsed >= thresholdSeconds) {
      nextPassed = true;
    } else if (!input && previousInput) {
      nextPassed = false;
    } else {
      nextPassed = passed;
    }
    if (input && (!initialized || !previousInput)) {
      entryTimeSeconds = timeSeconds;
    }
    initialized = true;
    previousTimeSeconds = timeSeconds;
    previousInput = input;
    passed = nextPassed;
    elapsedOutput = elapsed;
    passedOutput = nextPassed;
  }

  public double elapsed() {
    return elapsedOutput;
  }

  public boolean passed() {
    return passedOutput;
  }
}
