package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Reals.MovingAverage} kernel: the
 * time-window mean of the input, integrated between steps and read back through a
 * ring buffer of checkpoints.
 */
public final class MovingAverage {
  private static final double MIN_WINDOW_SECONDS = 1.0e-5;

  private final double windowSeconds;
  private final int capacity;

  private double mu = 0.0;
  private double startTimeSeconds = 0.0;
  private double previousTimeSeconds = Double.NaN;
  private final double[] checkpointTimes;
  private final double[] checkpointMus;
  private int checkpointHead = 0;
  private int checkpointLength = 0;

  public MovingAverage(double windowSeconds) {
    this(windowSeconds, 64);
  }

  public MovingAverage(double windowSeconds, int checkpointCapacity) {
    if (checkpointCapacity < 2) {
      throw new IllegalArgumentException("MovingAverage needs at least two checkpoints");
    }
    this.windowSeconds = windowSeconds;
    this.capacity = checkpointCapacity;
    this.checkpointTimes = new double[checkpointCapacity];
    this.checkpointMus = new double[checkpointCapacity];
  }

  public void reset() {
    mu = 0.0;
    startTimeSeconds = 0.0;
    previousTimeSeconds = Double.NaN;
    checkpointHead = 0;
    checkpointLength = 0;
  }

  private int physicalIndex(int logicalIndex) {
    return (checkpointHead + logicalIndex) % capacity;
  }

  private double checkpointTime(int logicalIndex) {
    return checkpointTimes[physicalIndex(logicalIndex)];
  }

  private double checkpointMu(int logicalIndex) {
    return checkpointMus[physicalIndex(logicalIndex)];
  }

  private void prune(double cutoff) {
    while (checkpointLength > 1 && checkpointTime(1) <= cutoff) {
      checkpointHead = (checkpointHead + 1) % capacity;
      checkpointLength -= 1;
    }
  }

  private void store(double timeSeconds, double muNow) {
    if (checkpointLength > 0) {
      int last = physicalIndex(checkpointLength - 1);
      if (Double.doubleToRawLongBits(checkpointTimes[last])
          == Double.doubleToRawLongBits(timeSeconds)) {
        checkpointMus[last] = muNow;
        return;
      }
    }
    if (checkpointLength == capacity) {
      checkpointHead = (checkpointHead + 1) % capacity;
      checkpointLength -= 1;
    }
    int slot = physicalIndex(checkpointLength);
    checkpointTimes[slot] = timeSeconds;
    checkpointMus[slot] = muNow;
    checkpointLength += 1;
  }

  private double muAt(double target, double timeSeconds, double muNow) {
    if (checkpointLength == 0) {
      return muNow;
    }
    double firstTime = checkpointTime(0);
    double firstMu = checkpointMu(0);
    if (target <= firstTime) {
      return firstMu;
    }
    double previousTime = firstTime;
    double previousMu = firstMu;
    for (int index = 1; index < checkpointLength; index += 1) {
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
      double retainedLow = checkpointLength > 0 ? checkpointTime(0) : start;
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
