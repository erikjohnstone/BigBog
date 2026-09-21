package com.bactalk.g36.kernel;

/**
 * CDL-exact {@code Buildings.Controls.OBC.CDL.Reals.PIDWithReset} kernel.
 *
 * <p>Plain Java, no Niagara dependencies. Behaviour is pinned by the Open Control
 * Engine golden trace and by BACTalk's IR interpreter (tests/test_native_bog_kernels.py).
 * The kernel is stepped with an absolute time in seconds; the first step has dt = 0.
 */
public final class PidWithReset {
  public enum ControllerType { P, PI, PD, PID }

  private final boolean withIntegral;
  private final boolean withDerivative;
  private final boolean reverseActing;
  private final double k;
  private final double ti;
  private final double td;
  private final double r;
  private final double ni;
  private final double nd;
  private final double yMin;
  private final double yMax;
  private final double xiStart;
  private final double ydStart;
  private final double yReset;

  private double integral;
  private double derivativeState = 0.0;
  private boolean previousTrigger = false;
  private double previousTimeSeconds = Double.NaN;

  public PidWithReset(
      ControllerType controllerType,
      boolean reverseActing,
      double k,
      double ti,
      double td,
      double r,
      double ni,
      double nd,
      double yMin,
      double yMax,
      double xiStart,
      double ydStart,
      double yReset) {
    this.withIntegral = controllerType == ControllerType.PI || controllerType == ControllerType.PID;
    this.withDerivative = controllerType == ControllerType.PD || controllerType == ControllerType.PID;
    this.reverseActing = reverseActing;
    this.k = k;
    this.ti = ti;
    this.td = td;
    this.r = r;
    this.ni = ni;
    this.nd = nd;
    this.yMin = yMin;
    this.yMax = yMax;
    this.xiStart = xiStart;
    this.ydStart = ydStart;
    this.yReset = yReset;
    this.integral = xiStart;
  }

  public void reset() {
    integral = xiStart;
    derivativeState = 0.0;
    previousTrigger = false;
    previousTimeSeconds = Double.NaN;
  }

  public double step(double timeSeconds, double setpoint, double measurement, boolean trigger) {
    if (!Double.isFinite(timeSeconds) || !Double.isFinite(setpoint) || !Double.isFinite(measurement)) {
      throw new IllegalArgumentException("PIDWithReset inputs must be finite");
    }
    boolean firstTick = Double.isNaN(previousTimeSeconds);
    if (!firstTick && timeSeconds < previousTimeSeconds) {
      throw new IllegalArgumentException("PIDWithReset time must be monotonic");
    }
    double dt = firstTick ? 0.0 : timeSeconds - previousTimeSeconds;
    double reverseSign = reverseActing ? 1.0 : -1.0;
    double error = reverseSign * (setpoint - measurement) / r;
    double proportional = k * error;
    double derivativeGain = k * td;
    double derivativeTime = td / nd;
    double derivative = withDerivative
        ? (firstTick ? ydStart : (derivativeGain / derivativeTime) * (error - derivativeState))
        : 0.0;
    double integralOutput = withIntegral ? integral : 0.0;
    double proportionalDerivative = proportional + derivative;
    double unlimited = proportionalDerivative + integralOutput;
    double output = unlimited > yMax ? yMax : (unlimited < yMin ? yMin : unlimited);

    if (withIntegral) {
      boolean risingReset = trigger && !previousTrigger;
      if (risingReset) {
        integral = yReset - proportionalDerivative;
      } else {
        double antiWindup = (unlimited - output) / (k * ni);
        double correctedError = error - antiWindup;
        integral = integralOutput + (k / ti) * correctedError * dt;
      }
      previousTrigger = trigger;
    }
    if (withDerivative) {
      double initialDerivativeState = firstTick
          ? (Math.abs(derivativeGain) < 1.0e-15
              ? error
              : error - derivativeTime * ydStart / derivativeGain)
          : derivativeState;
      double ratio = dt / derivativeTime;
      derivativeState = (initialDerivativeState + ratio * error) / (1.0 + ratio);
    }
    previousTimeSeconds = timeSeconds;
    return output;
  }
}
