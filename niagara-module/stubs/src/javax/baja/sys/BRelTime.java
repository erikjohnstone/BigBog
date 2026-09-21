package javax.baja.sys;

/** CI stub of the relative-time simple. */
public final class BRelTime extends BSimple {
  private final long millis;

  private BRelTime(long millis) {
    this.millis = millis;
  }

  public static BRelTime make(long millis) {
    return new BRelTime(millis);
  }

  public static BRelTime makeSeconds(int seconds) {
    return new BRelTime(seconds * 1000L);
  }

  public long getMillis() {
    return millis;
  }

  public double getSeconds() {
    return millis / 1000.0;
  }

  @Override
  public Type getType() {
    return Sys.loadType(BRelTime.class);
  }
}
