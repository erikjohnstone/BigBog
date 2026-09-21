package javax.baja.sys;

/** CI stub. */
public abstract class Slot {
  private final String name;

  protected Slot(String name) {
    this.name = name;
  }

  public String getName() {
    return name;
  }
}
