package javax.baja.sys;

/** CI stub. */
public final class Sys {
  private Sys() {}

  public static Type loadType(Class<?> owner) {
    return new Type(owner);
  }
}
