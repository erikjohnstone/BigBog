package com.bactalk.g36.kernel;

/**
 * CDL.Conversions.RealToInteger: round half away from zero. Stateless; integers are
 * carried as numerics in the exported station, so the value is returned as a double.
 */
public final class Round {
  public void reset() {}

  public double step(double input) {
    return input > 0.0 ? Math.floor(input + 0.5) : Math.ceil(input - 0.5);
  }
}
