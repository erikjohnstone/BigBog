within BACTalk;
package CdlSubstitutes "CDL block diagrams equal to LBNL plant utilities written as equations"
  annotation (Documentation(info="<html>
<p>
Each block here has the interface and parameters of one
<code>Buildings.Templates.Plants.Controls.Utilities</code> class that LBNL writes as
Modelica equations or an algorithm, which the Open Control Engine cannot execute. The
block computes the same outputs as a CDL block diagram, so the engine can run a
controller that contains it. Each is checked against the equations it replaces
(tests/test_cdl_substitutes.py; docs/decisions/016).
</p>
</html>"));
end CdlSubstitutes;
