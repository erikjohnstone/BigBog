package javax.baja.status;

import javax.baja.sys.BValue;

/** CI stub. */
public abstract class BStatusValue extends BValue {
  private BStatus status = BStatus.ok;

  public BStatus getStatus() {
    return status;
  }

  public void setStatus(BStatus status) {
    this.status = status;
  }

  public void setStatusNull(boolean isNull) {
    status = isNull ? BStatus.NULL : BStatus.ok;
  }
}
