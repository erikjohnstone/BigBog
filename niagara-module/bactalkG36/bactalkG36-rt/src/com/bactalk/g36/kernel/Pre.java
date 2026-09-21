package com.bactalk.g36.kernel;

/**
 * {@code Buildings.Controls.OBC.CDL.Logical.Pre} under the {@code host_tick_v1}
 * execution profile: the output is the input of the previous execution cycle.
 */
public final class Pre {
  private final boolean initial;
  private boolean previous;

  public Pre(boolean initial) {
    this.initial = initial;
    this.previous = initial;
  }

  public void reset() {
    previous = initial;
  }

  public boolean step(boolean current) {
    boolean output = previous;
    previous = current;
    return output;
  }
}
