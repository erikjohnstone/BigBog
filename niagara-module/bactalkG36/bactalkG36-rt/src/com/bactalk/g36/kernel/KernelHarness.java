package com.bactalk.g36.kernel;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Drives one kernel from a line protocol on standard input, so BACTalk's tests can
 * compare the Java kernels against the IR interpreter and the OCE goldens without
 * a Niagara runtime.
 *
 * <pre>
 * kernel TrueDelay
 * param delaySeconds=1800
 * param delayOnInit=false
 * row 0 1
 * row 60 1
 * end
 * </pre>
 *
 * Each {@code row} carries the absolute time in seconds followed by the kernel's
 * inputs (booleans as 0/1). One output line per row, values comma-separated,
 * booleans as {@code true}/{@code false}, doubles via {@link Double#toString}.
 */
public final class KernelHarness {
  private KernelHarness() {}

  public static void main(String[] args) throws IOException {
    BufferedReader reader =
        new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    String kernel = null;
    Map<String, String> params = new LinkedHashMap<>();
    StringBuilder out = new StringBuilder();
    Stepper stepper = null;
    String line;
    while ((line = reader.readLine()) != null) {
      line = line.trim();
      if (line.isEmpty() || line.startsWith("#")) {
        continue;
      }
      if (line.startsWith("kernel ")) {
        kernel = line.substring(7).trim();
      } else if (line.startsWith("param ")) {
        String[] pair = line.substring(6).split("=", 2);
        params.put(pair[0].trim(), pair.length > 1 ? pair[1].trim() : "");
      } else if (line.startsWith("row ")) {
        if (stepper == null) {
          stepper = build(kernel, params);
        }
        String[] parts = line.substring(4).trim().split("\\s+");
        double[] values = new double[parts.length];
        for (int index = 0; index < parts.length; index += 1) {
          values[index] = Double.parseDouble(parts[index]);
        }
        out.append(stepper.step(values)).append('\n');
      } else if (line.equals("end")) {
        break;
      } else {
        throw new IllegalArgumentException("unknown harness line: " + line);
      }
    }
    System.out.print(out);
    System.out.flush();
  }

  interface Stepper {
    String step(double[] row);
  }

  private static double num(Map<String, String> params, String key, double fallback) {
    String value = params.get(key);
    return value == null ? fallback : Double.parseDouble(value);
  }

  private static double num(Map<String, String> params, String key) {
    String value = params.get(key);
    if (value == null) {
      throw new IllegalArgumentException("missing parameter " + key);
    }
    return Double.parseDouble(value);
  }

  private static boolean bool(Map<String, String> params, String key, boolean fallback) {
    String value = params.get(key);
    return value == null ? fallback : Boolean.parseBoolean(value);
  }

  private static boolean b(double value) {
    return value != 0.0;
  }

  static Stepper build(String kernel, Map<String, String> params) {
    if (kernel == null) {
      throw new IllegalArgumentException("kernel line missing");
    }
    switch (kernel) {
      case "PidWithReset": {
        PidWithReset k = new PidWithReset(
            PidWithReset.ControllerType.valueOf(
                params.getOrDefault("controllerType", "PI").toUpperCase(Locale.ROOT)),
            bool(params, "reverseActing", false),
            num(params, "k"),
            num(params, "ti"),
            num(params, "td"),
            num(params, "r", 1.0),
            num(params, "ni", 0.9),
            num(params, "nd", 10.0),
            num(params, "yMin"),
            num(params, "yMax"),
            num(params, "xiStart", 0.0),
            num(params, "ydStart", 0.0),
            num(params, "yReset", 0.0));
        return row -> Double.toString(k.step(row[0], row[1], row[2], b(row[3])));
      }
      case "TrueDelay": {
        TrueDelay k = new TrueDelay(num(params, "delaySeconds"), bool(params, "delayOnInit", false));
        return row -> Boolean.toString(k.step(row[0], b(row[1])));
      }
      case "Timer": {
        Timer k = new Timer(num(params, "thresholdSeconds", 0.0));
        return row -> {
          k.step(row[0], b(row[1]));
          return Double.toString(k.elapsed()) + "," + Boolean.toString(k.passed());
        };
      }
      case "TimerWithReset": {
        TimerWithReset k = new TimerWithReset(num(params, "thresholdSeconds", 0.0));
        return row -> {
          k.step(row[0], b(row[1]), b(row[2]));
          return Double.toString(k.elapsed()) + "," + Boolean.toString(k.passed());
        };
      }
      case "TimerAccumulating": {
        TimerAccumulating k = new TimerAccumulating(num(params, "thresholdSeconds", 0.0));
        return row -> {
          k.step(row[0], b(row[1]), b(row[2]));
          return Double.toString(k.elapsed()) + "," + Boolean.toString(k.passed());
        };
      }
      case "TrueFalseHold": {
        TrueFalseHold k = new TrueFalseHold(
            num(params, "trueHoldSeconds"), num(params, "falseHoldSeconds"));
        return row -> Boolean.toString(k.step(row[0], b(row[1])));
      }
      case "Pre": {
        Pre k = new Pre(bool(params, "initial", false));
        return row -> Boolean.toString(k.step(b(row[1])));
      }
      case "UnitDelay": {
        UnitDelay k = new UnitDelay(num(params, "samplePeriodSeconds"), num(params, "initial", 0.0));
        return row -> Double.toString(k.step(row[0], row[1]));
      }
      case "FirstOrderHold": {
        FirstOrderHold k = new FirstOrderHold(num(params, "samplePeriodSeconds"));
        return row -> Double.toString(k.step(row[0], row[1]));
      }
      case "MovingAverage": {
        MovingAverage k = new MovingAverage(num(params, "windowSeconds"));
        return row -> Double.toString(k.step(row[0], row[1]));
      }
      case "TrimAndRespond": {
        boolean hold = bool(params, "holdEnabled", false);
        TrimAndRespond k = new TrimAndRespond(
            num(params, "initialSetpoint"),
            num(params, "minimumSetpoint"),
            num(params, "maximumSetpoint"),
            num(params, "delaySeconds"),
            num(params, "samplePeriodSeconds"),
            num(params, "ignoredRequests"),
            num(params, "trimAmount"),
            num(params, "respondAmount"),
            num(params, "maximumResponse"),
            hold,
            num(params, "holdDurationSeconds", 0.0));
        return row -> Double.toString(
            hold ? k.step(row[0], row[1], b(row[2]), b(row[3])) : k.step(row[0], row[1], b(row[2])));
      }
      case "BooleanInitialization": {
        BooleanInitialization k = new BooleanInitialization(bool(params, "initial", false));
        return row -> Boolean.toString(k.step(b(row[1])));
      }
      case "NumericChange": {
        NumericChange k = new NumericChange(
            NumericChange.Mode.valueOf(
                params.getOrDefault("mode", "CHANGED").toUpperCase(Locale.ROOT)),
            num(params, "initial", 0.0));
        return row -> Boolean.toString(k.step(row[1]));
      }
      default:
        throw new IllegalArgumentException("unknown kernel " + kernel);
    }
  }
}
