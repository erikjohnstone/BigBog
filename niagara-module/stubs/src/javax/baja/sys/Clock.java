package javax.baja.sys;

/** CI stub of the station clock and its scheduling tickets. */
public final class Clock {
  private Clock() {}

  public interface Ticket {
    void cancel();
  }

  public static long millis() {
    return System.currentTimeMillis();
  }

  public static Ticket schedule(BComponent target, BRelTime delay, Action action, BValue argument) {
    return () -> {};
  }
}
