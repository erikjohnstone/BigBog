package com.bactalk.g36.kernel;

/**
 * CDL.Reals.LimitSlewRate as the reference engine discretises it: the first execution
 * passes the input through; each later one takes an implicit first-order lag toward the
 * input over the elapsed time and clamps the change to fallingSlewRate*dt .. raisingSlewRate*dt.
 */
public final class LimitSlewRate {
  private final double raising;
  private final double falling;
  private final double tdSeconds;
  private final boolean enable;
  private double y;
  private double previousTime;

  public LimitSlewRate(double raising, double falling, double tdSeconds, boolean enable) {
    if (!(raising > 0.0) || !(falling < 0.0) || !(tdSeconds > 0.0)) {
      throw new IllegalArgumentException("LimitSlewRate needs raising > 0, falling < 0 and Td > 0");
    }
    this.raising = raising;
    this.falling = falling;
    this.tdSeconds = tdSeconds;
    this.enable = enable;
    reset();
  }

  public void reset() {
    y = Double.NaN;
    previousTime = Double.NaN;
  }

  public double step(double timeSeconds, double input) {
    if (!enable || Double.isNaN(previousTime)) {
      y = input;
    } else {
      double dt = timeSeconds - previousTime;
      if (dt > 0.0) {
        double alpha = dt / tdSeconds;
        double filtered = (y + alpha * input) / (1.0 + alpha);
        double change = Math.min(Math.max(filtered - y, falling * dt), raising * dt);
        y = y + change;
      }
    }
    previousTime = timeSeconds;
    return y;
  }
}
