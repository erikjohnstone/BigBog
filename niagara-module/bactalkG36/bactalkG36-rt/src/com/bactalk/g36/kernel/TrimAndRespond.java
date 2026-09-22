package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.ASHRAE.G36.Generic.TrimAndRespond} kernel,
 * with the optional {@code have_hol} hold input.
 *
 * <p>The expanded CDL composite (TrueDelay, Sampler, UnitDelay, the request logic and,
 * with hold, a TrueFalseHold, a SampleTrigger and a clear-dominant Latch) is folded
 * into one stepper. Behaviour is pinned by the OCE golden traces.
 */
public final class TrimAndRespond {
  private final double initialSetpoint;
  private final double minimumSetpoint;
  private final double maximumSetpoint;
  private final double delaySeconds;
  private final double samplePeriodSeconds;
  private final double ignoredRequests;
  private final double trimAmount;
  private final double respondAmount;
  private final double maximumResponse;
  private final boolean holdEnabled;
  private final double holdDurationSeconds;

  private boolean delayOut = false;
  private boolean delayPending = false;
  private double delayElapsed = 0.0;
  private boolean samplerInitialized = false;
  private double samplerHeld = 0.0;
  private double samplerT0 = 0.0;
  private long samplerLastIndex = -1L;
  private boolean unitInitialized = false;
  private double unitHeld;
  private double unitStaged;
  private double unitT0 = 0.0;
  private long unitLastIndex = -1L;
  private double previousTimeSeconds = Double.NaN;
  private boolean holdInitialized = false;
  private boolean holdOut = false;
  private double holdElapsed = 0.0;
  private boolean holdLatch = false;
  private long sampleTriggerLastIndex = -1L;

  public TrimAndRespond(
      double initialSetpoint,
      double minimumSetpoint,
      double maximumSetpoint,
      double delaySeconds,
      double samplePeriodSeconds,
      double ignoredRequests,
      double trimAmount,
      double respondAmount,
      double maximumResponse) {
    this(
        initialSetpoint,
        minimumSetpoint,
        maximumSetpoint,
        delaySeconds,
        samplePeriodSeconds,
        ignoredRequests,
        trimAmount,
        respondAmount,
        maximumResponse,
        false,
        0.0);
  }

  public TrimAndRespond(
      double initialSetpoint,
      double minimumSetpoint,
      double maximumSetpoint,
      double delaySeconds,
      double samplePeriodSeconds,
      double ignoredRequests,
      double trimAmount,
      double respondAmount,
      double maximumResponse,
      boolean holdEnabled,
      double holdDurationSeconds) {
    if (!(samplePeriodSeconds > 0.0)) {
      throw new IllegalArgumentException("TrimAndRespond sample period must be positive");
    }
    this.initialSetpoint = initialSetpoint;
    this.minimumSetpoint = minimumSetpoint;
    this.maximumSetpoint = maximumSetpoint;
    this.delaySeconds = delaySeconds;
    this.samplePeriodSeconds = samplePeriodSeconds;
    this.ignoredRequests = ignoredRequests;
    this.trimAmount = trimAmount;
    this.respondAmount = respondAmount;
    this.maximumResponse = maximumResponse;
    this.holdEnabled = holdEnabled;
    this.holdDurationSeconds = holdDurationSeconds;
    this.unitHeld = initialSetpoint;
    this.unitStaged = initialSetpoint;
  }

  public boolean hasHold() {
    return holdEnabled;
  }

  public void reset() {
    delayOut = false;
    delayPending = false;
    delayElapsed = 0.0;
    samplerInitialized = false;
    samplerHeld = 0.0;
    samplerT0 = 0.0;
    samplerLastIndex = -1L;
    unitInitialized = false;
    unitHeld = initialSetpoint;
    unitStaged = initialSetpoint;
    unitT0 = 0.0;
    unitLastIndex = -1L;
    previousTimeSeconds = Double.NaN;
    holdInitialized = false;
    holdOut = false;
    holdElapsed = 0.0;
    holdLatch = false;
    sampleTriggerLastIndex = -1L;
  }

  /** Step without a hold input (the {@code have_hol=false} variant). */
  public double step(double timeSeconds, double requestCount, boolean deviceOn) {
    return step(timeSeconds, requestCount, deviceOn, false);
  }

  public double step(double timeSeconds, double requestCount, boolean deviceOn, boolean hold) {
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(requestCount)) {
      throw new IllegalArgumentException("TrimAndRespond inputs must be finite");
    }
    boolean firstTick = Double.isNaN(previousTimeSeconds);
    if (!firstTick && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("TrimAndRespond time must be monotonic");
    }
    double dt = firstTick ? 0.0 : timeSeconds - previousTimeSeconds;
    double trueDelay = delaySeconds + samplePeriodSeconds;
    boolean holdReset = false;
    if (holdEnabled) {
      if (!holdInitialized) {
        holdInitialized = true;
        holdOut = hold;
        holdElapsed = 0.0;
      } else {
        holdElapsed += dt;
        if (hold != holdOut) {
          double requiredHold = holdOut ? holdDurationSeconds : 0.0;
          if (holdElapsed >= requiredHold) {
            holdOut = hold;
            holdElapsed = 0.0;
          }
        }
      }
      long triggerIndex = (long) Math.floor(timeSeconds / samplePeriodSeconds + 1.0e-9);
      if (triggerIndex > sampleTriggerLastIndex) {
        sampleTriggerLastIndex = triggerIndex;
        // Exact CDL Latch result at each clock: clear-dominant, so y = holdOut.
        holdLatch = holdOut;
      }
      holdReset = holdLatch;
    }

    if (deviceOn == delayOut) {
      delayElapsed = 0.0;
      delayPending = deviceOn;
    } else if (deviceOn != delayPending) {
      delayPending = deviceOn;
      delayElapsed = 0.0;
      if (!deviceOn || trueDelay <= 0.0) {
        delayOut = deviceOn;
      }
    } else {
      delayElapsed += dt;
      double activeDelay = deviceOn ? trueDelay : 0.0;
      if (delayElapsed >= activeDelay) {
        delayOut = deviceOn;
        delayElapsed = 0.0;
      }
    }

    if (!samplerInitialized) {
      samplerT0 = Math.floor(timeSeconds / samplePeriodSeconds) * samplePeriodSeconds;
      samplerLastIndex = (long) Math.floor((timeSeconds - samplerT0) / samplePeriodSeconds + 1.0e-9);
      samplerInitialized = true;
      samplerHeld = requestCount;
    } else {
      long sampleIndex = (long) Math.floor((timeSeconds - samplerT0) / samplePeriodSeconds + 1.0e-9);
      if (sampleIndex > samplerLastIndex) {
        samplerLastIndex = sampleIndex;
        samplerHeld = requestCount;
      } else if (Math.abs(timeSeconds - (samplerT0 + samplerLastIndex * samplePeriodSeconds))
          <= 1.0e-9) {
        samplerHeld = requestCount; // still at the sample instant: last input wins
      }
    }

    boolean unitDue = false;
    double unitOutput;
    if (!unitInitialized) {
      unitOutput = initialSetpoint;
    } else {
      long unitIndex = (long) Math.floor((timeSeconds - unitT0) / samplePeriodSeconds + 1.0e-9);
      unitDue = unitIndex > unitLastIndex;
      unitOutput = unitDue ? unitStaged : unitHeld;
    }

    double requestDelta = samplerHeld - ignoredRequests;
    double response = Math.copySign(
        Math.min(Math.abs(respondAmount) * requestDelta, Math.abs(maximumResponse)),
        respondAmount);
    double netReset;
    if (holdReset) {
      netReset = 0.0;
    } else if (!delayOut) {
      netReset = 0.0;
    } else if (requestDelta > 0.0) {
      netReset = trimAmount + response;
    } else {
      netReset = trimAmount;
    }
    double candidate = Math.max(minimumSetpoint, Math.min(maximumSetpoint, unitOutput + netReset));
    double output = deviceOn ? candidate : initialSetpoint;

    if (!unitInitialized) {
      unitT0 = Math.floor(timeSeconds / samplePeriodSeconds) * samplePeriodSeconds;
      unitInitialized = true;
      unitLastIndex = (long) Math.floor((timeSeconds - unitT0) / samplePeriodSeconds + 1.0e-9);
      unitStaged = output;
    } else if (unitDue) {
      unitLastIndex = (long) Math.floor((timeSeconds - unitT0) / samplePeriodSeconds + 1.0e-9);
      unitHeld = unitStaged;
      unitStaged = output;
    }
    previousTimeSeconds = timeSeconds;
    return output;
  }
}
