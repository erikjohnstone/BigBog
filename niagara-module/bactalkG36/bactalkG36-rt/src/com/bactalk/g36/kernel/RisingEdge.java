package com.bactalk.g36.kernel;

/**
 * Rising-edge detector with host-tick semantics ({@code one_shot} in the IR): true for
 * exactly one execution when the input is true and was false at the previous execution.
 * It is stepped only on the execution period, so a transient value inside one link
 * propagation is never mistaken for an edge (docs/niagara-semantics.md, S-LINK-4).
 */
public final class RisingEdge {
  private final boolean initial;
  private boolean previous;

  public RisingEdge(boolean initial) {
    this.initial = initial;
    this.previous = initial;
  }

  public void reset() {
    previous = initial;
  }

  public boolean step(boolean input) {
    boolean pulse = input && !previous;
    previous = input;
    return pulse;
  }
}
