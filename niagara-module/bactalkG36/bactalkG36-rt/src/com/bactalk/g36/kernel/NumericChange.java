package com.bactalk.g36.kernel;

/**
 * Numeric change detector behind the {@code numeric_changed}, {@code numeric_increased}
 * and {@code numeric_decreased} IR kinds: true on the cycle the input differs from
 * the previous cycle in the configured direction.
 */
public final class NumericChange {
  public enum Mode { CHANGED, INCREASED, DECREASED }

  private final Mode mode;
  private final double initial;
  private double previous;

  public NumericChange(Mode mode, double initial) {
    this.mode = mode;
    this.initial = initial;
    this.previous = initial;
  }

  public void reset() {
    previous = initial;
  }

  public boolean step(double current) {
    if (!Double.isFinite(current)) {
      throw new IllegalArgumentException("change-detector input must be finite");
    }
    boolean result;
    switch (mode) {
      case INCREASED:
        result = current > previous;
        break;
      case DECREASED:
        result = current < previous;
        break;
      default:
        result = current != previous;
        break;
    }
    previous = current;
    return result;
  }
}
