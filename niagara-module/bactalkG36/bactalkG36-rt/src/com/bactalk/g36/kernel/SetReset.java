package com.bactalk.g36.kernel;

/**
 * Clear-dominant set/reset latch with host-tick semantics ({@code boolean_set_reset},
 * {@code CDL.Logical.Latch}): a rising edge on {@code set} raises the output, {@code clear}
 * forces it low and wins when both are true.
 */
public final class SetReset {
  private boolean output = false;
  private boolean previousSet = false;

  public void reset() {
    output = false;
    previousSet = false;
  }

  public boolean step(boolean set, boolean clear) {
    boolean next = !clear && ((set && !previousSet) || output);
    output = next;
    previousSet = set;
    return next;
  }
}
