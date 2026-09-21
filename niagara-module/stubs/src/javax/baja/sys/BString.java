package javax.baja.sys;

/** CI stub. */
public final class BString extends BSimple {
  private final String value;

  private BString(String value) {
    this.value = value;
  }

  public static BString make(String value) {
    return new BString(value);
  }

  public String getString() {
    return value;
  }

  @Override
  public Type getType() {
    return Sys.loadType(BString.class);
  }
}
