package javax.baja.status;

import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CI stub. */
public final class BStatusBoolean extends BStatusValue {
  private boolean value;

  public BStatusBoolean() {
    this(false);
  }

  public BStatusBoolean(boolean value) {
    this.value = value;
  }

  public BStatusBoolean(boolean value, BStatus status) {
    this.value = value;
    setStatus(status);
  }

  public boolean getValue() {
    return value;
  }

  public void setValue(boolean value) {
    this.value = value;
  }

  @Override
  public Type getType() {
    return Sys.loadType(BStatusBoolean.class);
  }
}
