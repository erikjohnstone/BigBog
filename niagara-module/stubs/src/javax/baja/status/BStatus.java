package javax.baja.status;

import javax.baja.sys.BSimple;
import javax.baja.sys.Sys;
import javax.baja.sys.Type;

/** CI stub of the status bit set. */
public final class BStatus extends BSimple {
  public static final int OK_BITS = 0;
  public static final int NULL_BITS = 0x0001;
  public static final int FAULT_BITS = 0x0002;
  public static final int DOWN_BITS = 0x0004;
  public static final int STALE_BITS = 0x0010;

  public static final BStatus ok = new BStatus(OK_BITS);
  public static final BStatus NULL = new BStatus(NULL_BITS);
  public static final BStatus fault = new BStatus(FAULT_BITS);
  public static final BStatus stale = new BStatus(STALE_BITS);

  private final int bits;

  private BStatus(int bits) {
    this.bits = bits;
  }

  public static BStatus make(int bits) {
    return new BStatus(bits);
  }

  public int getBits() {
    return bits;
  }

  public boolean isNull() {
    return (bits & NULL_BITS) != 0;
  }

  public boolean isFault() {
    return (bits & FAULT_BITS) != 0;
  }

  public boolean isStale() {
    return (bits & STALE_BITS) != 0;
  }

  /** True when the value can be used for control: not null, fault, down or stale. */
  public boolean isValid() {
    return (bits & (NULL_BITS | FAULT_BITS | DOWN_BITS | STALE_BITS)) == 0;
  }

  @Override
  public Type getType() {
    return Sys.loadType(BStatus.class);
  }
}
