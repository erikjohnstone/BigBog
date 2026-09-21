package javax.baja.status;

import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CI stub. */
public final class BStatusNumeric extends BStatusValue {
  private double value;

  public BStatusNumeric() {
    this(0.0);
  }

  public BStatusNumeric(double value) {
    this.value = value;
  }

  public BStatusNumeric(double value, BStatus status) {
    this.value = value;
    setStatus(status);
  }

  public double getValue() {
    return value;
  }

  public void setValue(double value) {
    this.value = value;
  }

  @Override
  public Type getType() {
    return Sys.loadType(BStatusNumeric.class);
  }
}
