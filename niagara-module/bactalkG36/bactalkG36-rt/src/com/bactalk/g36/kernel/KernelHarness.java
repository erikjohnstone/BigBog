package com.bactalk.g36.kernel;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
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
 *
 * <p>The same process also serves the Shadow Runtime's JVM sidecar with a session
 * protocol that keeps many kernels open and answers every step at once:
 *
 * <pre>
 * open k1 TrueDelay delaySeconds=1800 delayOnInit=false
 * step k1 0 1
 * close k1
 * end
 * </pre>
 *
 * {@code open} answers {@code ok <id>}, {@code step} answers the kernel's output
 * line, {@code close} answers {@code ok <id>}; each answer is flushed immediately.
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
    Map<String, Stepper> session = new LinkedHashMap<>();
    PrintStream reply = new PrintStream(System.out, true, StandardCharsets.UTF_8);
    String line;
    while ((line = reader.readLine()) != null) {
      line = line.trim();
      if (line.isEmpty() || line.startsWith("#")) {
        continue;
      }
      if (line.startsWith("open ")) {
        String[] parts = line.substring(5).trim().split("\\s+");
        if (parts.length < 2) {
          throw new IllegalArgumentException("open needs an id and a kernel: " + line);
        }
        Map<String, String> opened = new LinkedHashMap<>();
        for (int index = 2; index < parts.length; index += 1) {
          String[] pair = parts[index].split("=", 2);
          opened.put(pair[0].trim(), pair.length > 1 ? pair[1].trim() : "");
        }
        session.put(parts[0], build(parts[1], opened));
        reply.println("ok " + parts[0]);
      } else if (line.startsWith("step ")) {
        String[] parts = line.substring(5).trim().split("\\s+");
        Stepper target = session.get(parts[0]);
        if (target == null) {
          throw new IllegalArgumentException("unknown session id " + parts[0]);
        }
        double[] values = new double[parts.length - 1];
        for (int index = 1; index < parts.length; index += 1) {
          values[index - 1] = Double.parseDouble(parts[index]);
        }
        reply.println(target.step(values));
      } else if (line.startsWith("close ")) {
        String id = line.substring(6).trim();
        session.remove(id);
        reply.println("ok " + id);
      } else if (line.startsWith("kernel ")) {
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
      case "Round": {
        Round k = new Round();
        return row -> Double.toString(k.step(row[1]));
      }
      case "LimitSlewRate": {
        LimitSlewRate k = new LimitSlewRate(
            num(params, "raisingSlewRate"),
            num(params, "fallingSlewRate"),
            num(params, "tdSeconds"),
            bool(params, "enable", true));
        return row -> Double.toString(k.step(row[0], row[1]));
      }
      case "IntegratorWithReset": {
        IntegratorWithReset k =
            new IntegratorWithReset(num(params, "gain", 1.0), num(params, "initial", 0.0));
        return row -> Double.toString(k.step(row[0], row[1], row[2], b(row[3])));
      }
      case "OnCounter": {
        OnCounter k = new OnCounter(num(params, "initial", 0.0));
        return row -> Double.toString(k.step(row[0], b(row[1]), b(row[2])));
      }
      case "WetBulb": {
        WetBulb k = new WetBulb();
        return row -> Double.toString(k.step(row[0], row[1], row[2]));
      }
      case "RisingEdge": {
        RisingEdge k = new RisingEdge(bool(params, "initial", false));
        return row -> Boolean.toString(k.step(b(row[1])));
      }
      case "FallingEdge": {
        FallingEdge k = new FallingEdge(bool(params, "initial", false));
        return row -> Boolean.toString(k.step(b(row[1])));
      }
      case "SetReset": {
        SetReset k = new SetReset();
        return row -> Boolean.toString(k.step(b(row[1]), b(row[2])));
      }
      case "Sampler": {
        Sampler k = new Sampler(num(params, "samplePeriodSeconds"));
        return row -> Double.toString(k.step(row[0], row[1]));
      }
      case "SampleTrigger": {
        SampleTrigger k = new SampleTrigger(num(params, "periodSeconds"), num(params, "shiftSeconds", 0.0));
        return row -> Boolean.toString(k.step(row[0]));
      }
      case "Hysteresis": {
        Hysteresis k = new Hysteresis(num(params, "uLow"), num(params, "uHigh"), bool(params, "initial", false));
        return row -> Boolean.toString(k.step(row[1]));
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
