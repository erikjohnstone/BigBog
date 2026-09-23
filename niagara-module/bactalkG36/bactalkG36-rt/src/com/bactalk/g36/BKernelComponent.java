package com.bactalk.g36;

import javax.baja.status.BStatus;
import javax.baja.status.BStatusValue;
import javax.baja.sys.Action;
import javax.baja.sys.BComponent;
import javax.baja.sys.BRelTime;
import javax.baja.sys.Clock;
import javax.baja.sys.Context;
import javax.baja.sys.Flags;
import javax.baja.sys.Property;

/**
 * Base of every bactalkG36 component: owns the execution ticket, the time base and
 * the status policy. Subclasses map their slots onto one plain-Java kernel from
 * {@code com.bactalk.g36.kernel}.
 *
 * <p>Status policy: when any input is null, fault, down or stale the outputs are
 * marked null and the kernel is not stepped, so a bad sensor never advances a
 * timer or an integral. Outputs return to ok on the next valid execution.
 *
 * <p>Time base: seconds since the component started, from the station clock, so
 * every kernel sees monotonic absolute time regardless of the execution period.
 *
 * <p>Execution: every executionPeriod only (see {@link #stepsOnInputChange()}); a
 * parameter change rebuilds the kernel and steps it at once.
 */
public abstract class BKernelComponent extends BComponent {
  /** How often the kernel is stepped even when no input changes. */
  public static final Property executionPeriod =
      newProperty(0, BRelTime.makeSeconds(1), null);

  /** Steps the kernel; scheduled by the ticket and fired by input changes. */
  public static final Action execute = newAction(Flags.HIDDEN, null);

  /**
   * Re-steps a sampling kernel at the instant of its last tick once the rest of the
   * station has settled (a zero-delay ticket runs after the engine queue drains), so
   * the value it samples at a period boundary is the settled one, as a CDL solver
   * samples after event iteration. Only kernels with {@link #resamplesAtInstantEnd()}.
   */
  public static final Action resample = newAction(Flags.HIDDEN, null);

  /**
   * Executes the kernel once at station start, after the links have delivered their start
   * values (S-LINK-2 / S-MODULE-7, docs/decisions/016): every component contributes its
   * first output at t = 0 instead of one execution period later.
   */
  public static final Action startExecute = newAction(Flags.HIDDEN, null);

  /**
   * Rebuilds the kernel and steps it once more at the end of the start instant, for a
   * kernel whose first output ignores its input ({@link #latchesAtStart()}): it latches
   * the settled start input, as CDL's Pre does at t = 0, and leaves its output unchanged.
   */
  public static final Action latch = newAction(Flags.HIDDEN, null);

  private Clock.Ticket ticket;
  private long startedMillis;
  private double lastTickSeconds = Double.NaN;
  private boolean resamplePending;

  public BRelTime getExecutionPeriod() {
    return (BRelTime) get(executionPeriod);
  }

  @Override
  public void started() throws Exception {
    super.started();
    startedMillis = Clock.millis();
    rebuildKernel();
    schedule();
    Clock.schedule(this, BRelTime.make(0), startExecute, null);
  }

  public void doStartExecute() {
    doExecute();
    if (isRunning() && latchesAtStart()) {
      Clock.schedule(this, BRelTime.make(0), latch, null);
    }
  }

  public void doLatch() {
    if (!isRunning() || !inputsValid()) {
      return;
    }
    rebuildKernel();
    step(0.0);
  }

  /** Whether the kernel's first output ignores its input, so it latches the settled start input. */
  protected boolean latchesAtStart() {
    return false;
  }

  @Override
  public void stopped() throws Exception {
    cancel();
    super.stopped();
  }

  @Override
  public void changed(Property property, Context context) {
    super.changed(property, context);
    if (!isRunning()) {
      return;
    }
    if (isParameter(property)) {
      rebuildKernel();
      doExecute();
    } else if (isInput(property) && stepsOnInputChange()) {
      doExecute();
    }
  }

  /**
   * Whether an input change steps the kernel at once. Since N7 no component does: every
   * kernel samples its inputs on the execution period only (host-tick semantics), so a
   * transient value inside one link propagation can never restart a delay, latch an
   * edge or advance a per-execution state. Latency is bounded by executionPeriod.
   */
  protected boolean stepsOnInputChange() {
    return false;
  }

  public void doExecute() {
    if (!isRunning()) {
      return;
    }
    try {
      if (!inputsValid()) {
        markOutputsNull();
        return;
      }
      double timeSeconds = Math.max(0.0, (Clock.millis() - startedMillis) / 1000.0);
      lastTickSeconds = timeSeconds;
      step(timeSeconds);
      if (resamplesAtInstantEnd() && !resamplePending) {
        resamplePending = true;
        Clock.schedule(this, BRelTime.make(0), resample, null);
      }
    } finally {
      schedule();
    }
  }

  public void doResample() {
    resamplePending = false;
    if (!isRunning() || Double.isNaN(lastTickSeconds) || !inputsValid()) {
      return;
    }
    step(lastTickSeconds);
  }

  /** Whether the kernel samples its input at period boundaries and needs the settled value. */
  protected boolean resamplesAtInstantEnd() {
    return false;
  }

  protected static boolean valid(BStatusValue value) {
    return value != null && value.getStatus().isValid();
  }

  protected static void markNull(BStatusValue value) {
    value.setStatus(BStatus.NULL);
  }

  protected static void markOk(BStatusValue value) {
    value.setStatus(BStatus.ok);
  }

  protected static double seconds(BRelTime value) {
    return value.getMillis() / 1000.0;
  }

  private void schedule() {
    cancel();
    ticket = Clock.schedule(this, getExecutionPeriod(), execute, null);
  }

  private void cancel() {
    if (ticket != null) {
      ticket.cancel();
      ticket = null;
    }
  }

  /** Build (or rebuild) the kernel from the parameter slots and reset its state. */
  protected abstract void rebuildKernel();

  protected abstract boolean isInput(Property property);

  protected abstract boolean isParameter(Property property);

  protected abstract boolean inputsValid();

  protected abstract void markOutputsNull();

  protected abstract void step(double timeSeconds);
}
