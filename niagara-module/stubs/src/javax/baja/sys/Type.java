package javax.baja.sys;

/** CI stub. */
public final class Type {
  private final Class<?> owner;

  Type(Class<?> owner) {
    this.owner = owner;
  }

  public String getTypeName() {
    return owner.getSimpleName().substring(1);
  }
}
