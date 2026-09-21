package com.bactalk.g36.kernel;

/**
 * {@code Buildings.Templates.Plants.Controls.Utilities.Initialization} kernel: the
 * configured value on the first execution cycle, then the input.
 */
public final class BooleanInitialization {
  private final boolean initial;
  private boolean first = true;

  public BooleanInitialization(boolean initial) {
    this.initial = initial;
  }

  public void reset() {
    first = true;
  }

  public boolean step(boolean input) {
    if (first) {
      first = false;
      return initial;
    }
    return input;
  }
}
