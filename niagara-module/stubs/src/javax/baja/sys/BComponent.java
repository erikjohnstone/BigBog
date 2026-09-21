package javax.baja.sys;

import java.util.IdentityHashMap;
import java.util.Map;

/**
 * CI stub of the Niagara component base. Slots are declared in the classic style
 * ({@code public static final Property in = newProperty(...)}); the real runtime
 * derives slot names from the field names when the type is loaded.
 */
public abstract class BComponent extends BValue {
  private final Map<Property, Object> values = new IdentityHashMap<>();
  private boolean running = false;

  protected static Property newProperty(int flags, Object defaultValue, BFacets facets) {
    return new Property("", flags, defaultValue);
  }

  protected static Action newAction(int flags, BFacets facets) {
    return new Action("");
  }

  public Object get(Property property) {
    return values.getOrDefault(property, property.getDefaultValue());
  }

  public void set(Property property, BValue value) {
    values.put(property, value);
  }

  public void set(Property property, BValue value, Context context) {
    set(property, value);
  }

  public boolean isRunning() {
    return running;
  }

  public void started() throws Exception {
    running = true;
  }

  public void stopped() throws Exception {
    running = false;
  }

  public void changed(Property property, Context context) {}
}
