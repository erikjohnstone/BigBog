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
 * <p>Execution: every executionPeriod, and on each input change unless the kernel
 * is tick-semantic (see {@link #stepsOnInputChange()}).
 */
public abstract class BKernelComponent extends BComponent {
  /** How often the kernel is stepped even when no input changes. */
  public static final Property executionPeriod =
      newProperty(0, BRelTime.makeSeconds(1), null);

  /** Steps the kernel; scheduled by the ticket and fired by input changes. */
  public static final Action execute = newAction(Flags.HIDDEN, null);

  private Clock.Ticket ticket;
  private long startedMillis;

  public BRelTime getExecutionPeriod() {
    return (BRelTime) get(executionPeriod);
  }

  @Override
  public void started() throws Exception {
    super.started();
    startedMillis = Clock.millis();
    rebuildKernel();
    schedule();
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
   * Whether an input change steps the kernel at once. Kernels whose state advances
   * per execution rather than per unit of time (Pre, NumericChange) step only on the
   * execution period, so "the previous execution" means the previous host tick.
   */
  protected boolean stepsOnInputChange() {
    return true;
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
      step(timeSeconds);
    } finally {
      schedule();
    }
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
