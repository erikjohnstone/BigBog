package com.bactalk.g36.kernel;

/**
 * Falling-edge detector with host-tick semantics ({@code boolean_falling_edge}): true for
 * exactly one execution when the input is false and was true at the previous execution.
 */
public final class FallingEdge {
  private final boolean initial;
  private boolean previous;

  public FallingEdge(boolean initial) {
    this.initial = initial;
    this.previous = initial;
  }

  public void reset() {
    previous = initial;
  }

  public boolean step(boolean input) {
    boolean pulse = previous && !input;
    previous = input;
    return pulse;
  }
}
