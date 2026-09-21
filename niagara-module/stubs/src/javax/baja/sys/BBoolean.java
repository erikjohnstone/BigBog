package javax.baja.sys;

/** CI stub. */
public final class BBoolean extends BSimple {
  public static final BBoolean TRUE = new BBoolean(true);
  public static final BBoolean FALSE = new BBoolean(false);

  private final boolean value;

  private BBoolean(boolean value) {
    this.value = value;
  }

  public static BBoolean make(boolean value) {
    return value ? TRUE : FALSE;
  }

  public boolean getBoolean() {
    return value;
  }

  @Override
  public Type getType() {
    return Sys.loadType(BBoolean.class);
  }
}
