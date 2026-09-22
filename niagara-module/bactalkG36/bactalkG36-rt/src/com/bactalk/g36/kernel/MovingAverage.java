package com.bactalk.g36.kernel;

import java.util.ArrayList;
import java.util.List;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Reals.MovingAverage} kernel: the
 * time-window mean of the input, integrated between steps and read back through
 * checkpoints of the running integral.
 *
 * <p>Checkpoints are kept for the whole window and pruned by time, so the kernel
 * is exact at any execution period (a fixed 64-entry ring truncated windows longer
 * than 64 periods; found by the Shadow Runtime, GOAL-NATIVE-BOG.md N6).
 */
public final class MovingAverage {
  private static final double MIN_WINDOW_SECONDS = 1.0e-5;

  private final double windowSeconds;

  private double mu = 0.0;
  private double startTimeSeconds = 0.0;
  private double previousTimeSeconds = Double.NaN;
  private final List<double[]> checkpoints = new ArrayList<>();

  public MovingAverage(double windowSeconds) {
    this.windowSeconds = windowSeconds;
  }

  /** Kept for callers that sized the old ring; the capacity is ignored. */
  public MovingAverage(double windowSeconds, int checkpointCapacity) {
    this(windowSeconds);
    if (checkpointCapacity < 2) {
      throw new IllegalArgumentException("MovingAverage needs at least two checkpoints");
    }
  }

  public void reset() {
    mu = 0.0;
    startTimeSeconds = 0.0;
    previousTimeSeconds = Double.NaN;
    checkpoints.clear();
  }

  private double checkpointTime(int index) {
    return checkpoints.get(index)[0];
  }

  private double checkpointMu(int index) {
    return checkpoints.get(index)[1];
  }

  private void prune(double cutoff) {
    while (checkpoints.size() > 1 && checkpointTime(1) <= cutoff) {
      checkpoints.remove(0);
    }
  }

  private void store(double timeSeconds, double muNow) {
    if (!checkpoints.isEmpty()) {
      double[] last = checkpoints.get(checkpoints.size() - 1);
      if (Double.doubleToRawLongBits(last[0]) == Double.doubleToRawLongBits(timeSeconds)) {
        last[1] = muNow;
        return;
      }
    }
    checkpoints.add(new double[] {timeSeconds, muNow});
  }

  private double muAt(double target, double timeSeconds, double muNow) {
    int length = checkpoints.size();
    if (length == 0) {
      return muNow;
    }
    double firstTime = checkpointTime(0);
    double firstMu = checkpointMu(0);
    if (target <= firstTime) {
      return firstMu;
    }
    double previousTime = firstTime;
    double previousMu = firstMu;
    for (int index = 1; index < length; index += 1) {
      double nextTime = checkpointTime(index);
      double nextMu = checkpointMu(index);
      if (target <= nextTime) {
        double denominator = nextTime - previousTime;
        return denominator == 0.0
            ? nextMu
            : previousMu + (nextMu - previousMu) * ((target - previousTime) / denominator);
      }
      previousTime = nextTime;
      previousMu = nextMu;
    }
    if (target <= timeSeconds) {
      double denominator = timeSeconds - previousTime;
      return denominator == 0.0
          ? muNow
          : previousMu + (muNow - previousMu) * ((target - previousTime) / denominator);
    }
    return muNow;
  }

  public double step(double timeSeconds, double input) {
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(input)) {
      throw new IllegalArgumentException("MovingAverage inputs must be finite");
    }
    boolean firstTick = Double.isNaN(previousTimeSeconds);
    if (!firstTick && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("MovingAverage time must be monotonic");
    }
    double delta = Math.max(windowSeconds, MIN_WINDOW_SECONDS);
    double start = firstTick ? timeSeconds : startTimeSeconds;
    double dt = firstTick ? 0.0 : timeSeconds - previousTimeSeconds;
    double muNow = mu + input * dt;
    double target = timeSeconds - delta;
    double delayedMu = muAt(target, timeSeconds, muNow);
    double denominator;
    if (timeSeconds >= start + delta) {
      double retainedLow = checkpoints.isEmpty() ? start : checkpointTime(0);
      double low = Math.max(Math.max(target, retainedLow), start);
      denominator = Math.max(timeSeconds - low, MIN_WINDOW_SECONDS);
    } else {
      denominator = timeSeconds - start + 1.0e-3;
    }
    double output = (muNow - delayedMu) / denominator;
    if (firstTick) {
      startTimeSeconds = timeSeconds;
    }
    prune(target);
    store(timeSeconds, muNow);
    mu = muNow;
    previousTimeSeconds = timeSeconds;
    return output;
  }
}
