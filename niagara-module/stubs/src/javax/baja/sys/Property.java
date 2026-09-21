package javax.baja.sys;

/** CI stub. The real slot name is taken from the declaring field by Sys.loadType. */
public final class Property extends Slot {
  private final int flags;
  private final Object defaultValue;

  Property(String name, int flags, Object defaultValue) {
    super(name);
    this.flags = flags;
    this.defaultValue = defaultValue;
  }

  public int getFlags() {
    return flags;
  }

  public Object getDefaultValue() {
    return defaultValue;
  }
}
