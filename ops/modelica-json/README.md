# modelica-json compatibility boundary

BACTalk pins LBNL `modelica-json` and runs it as a bounded external build tool.
`modelica-mode-null-type.patch` adds a null guard before recursive component-type
inspection and removes insignificant whitespace from connector expressions before
constructing RDF node IRIs. Without those guards, valid parser output containing a
null `type_specifier` terminates Modelica-mode traversal with a JavaScript
`TypeError`, while expressions such as `outPort[nSta + 1]` are rejected by rdflib
because a NamedNode IRI cannot contain raw spaces.

The patch does not change generated control equations. `make cdl-oce-contract`
proves the normal G36 CDL path and extraction of an annotated controls instance
from a containing Modelica model. The full configured G36 multizone VAV model
does not complete inside the product's bounded translation window; Rumoca also
reports an unresolved parameter-derived conditional component. Those remain
explicit elaboration blockers rather than silently falling back to guessed
logic.
