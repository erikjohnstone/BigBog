package javax.baja.sys;

/** CI stub. */
public final class BDouble extends BSimple {
  private final double value;

  private BDouble(double value) {
    this.value = value;
  }

  public static BDouble make(double value) {
    return new BDouble(value);
  }

  public double getDouble() {
    return value;
  }

  @Override
  public Type getType() {
    return Sys.loadType(BDouble.class);
  }
}
