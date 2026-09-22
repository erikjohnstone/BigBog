package com.bactalk.g36.kernel;

/**
 * CDL.Integers.OnCounter as the reference engine discretises it: an execution returns the
 * count the previous instant left; the first instant only records the inputs, later ones
 * add one on a rising trigger and return to the start value on a rising reset (reset
 * wins). A second execution at the same instant recomputes from the instant's inputs.
 */
public final class OnCounter {
  private final double initial;
  private double count;
  private boolean previousTrigger;
  private boolean previousReset;
  private boolean history;
  private double instant;
  private double instantCount;
  private boolean instantTrigger;
  private boolean instantReset;
  private boolean instantHistory;

  public OnCounter(double initial) {
    if (!Double.isFinite(initial) || initial != Math.rint(initial)) {
      throw new IllegalArgumentException("OnCounter needs an integer start value");
    }
    this.initial = initial;
    reset();
  }

  public void reset() {
    count = initial;
    previousTrigger = false;
    previousReset = false;
    history = false;
    instant = Double.NaN;
  }

  public double step(double timeSeconds, boolean trigger, boolean resetInput) {
    if (!(timeSeconds == instant)) {
      instant = timeSeconds;
      instantCount = count;
      instantTrigger = previousTrigger;
      instantReset = previousReset;
      instantHistory = history;
    }
    count = instantCount;
    if (instantHistory
        && ((trigger && !instantTrigger) || (resetInput && !instantReset))) {
      count = resetInput ? initial : instantCount + 1.0;
    }
    previousTrigger = trigger;
    previousReset = resetInput;
    history = true;
    return instantCount;
  }
}
