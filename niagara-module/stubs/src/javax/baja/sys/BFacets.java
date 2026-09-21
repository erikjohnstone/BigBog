package javax.baja.sys;

/** CI stub. */
public final class BFacets extends BSimple {
  public static final BFacets NULL = new BFacets();

  public static BFacets makeNumeric(int precision, double min, double max) {
    return new BFacets();
  }

  @Override
  public Type getType() {
    return Sys.loadType(BFacets.class);
  }
}
