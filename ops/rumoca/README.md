# Rumoca Modelica elaboration boundary

BACTalk invokes pinned Apache-2.0 Rumoca as an isolated build tool and emits its
flattened JSON IR through the allowlisted G36 API. The Modelica Standard Library
is pinned separately under its BSD-3-Clause license.

Buildings v13 places `Evaluate=true` on two conditional `Dzero` block instances.
Rumoca 0.10.1 rejects that annotation because the Modelica Language Specification
limits `Evaluate` to parameters and constants. `modelica-buildings-compat.patch`
removes only those two optimization hints in a dedicated source checkout; it does
not alter equations, parameters, connections, or controller behavior.

`make rumoca-contract` proves a real G36 controller reaches flattened IR and keeps
the current full multizone VAV conditional-instantiation limitation explicit. A
successful flatten is compiler evidence, not Niagara runtime qualification.
