package com.bactalk.g36.kernel;

/**
 * CDL.Psychrometrics.WetBulb_TDryBulPhi: Stull's closed-form wet-bulb temperature [K] from
 * dry-bulb temperature [K] and relative humidity [1]. StrictMath.atan is fdlibm's, as is
 * the reference engine's libm; rh^1.5 is rh * sqrt(rh) here and in the Python port.
 */
public final class WetBulb {
  private static final double KELVIN_OFFSET = 273.15;

  public void reset() {}

  public double step(double timeSeconds, double dryBulb, double relativeHumidity) {
    if (!Double.isFinite(dryBulb) || !Double.isFinite(relativeHumidity)) {
      return Double.NaN;
    }
    double tC = dryBulb - KELVIN_OFFSET;
    double rh = 100.0 * relativeHumidity;
    if (!Double.isFinite(rh)) {
      return Double.NaN;
    }
    return KELVIN_OFFSET
        + tC * StrictMath.atan(0.151977 * StrictMath.sqrt(rh + 8.313659))
        + StrictMath.atan(tC + rh)
        - StrictMath.atan(rh - 1.676331)
        + 0.00391838 * (rh * StrictMath.sqrt(rh)) * StrictMath.atan(0.023101 * rh)
        - 4.686035;
  }
}
