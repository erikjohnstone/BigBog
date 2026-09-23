within BACTalk.CdlSubstitutes;
block MultiMaxInteger
  "Output the maximum element of the input vector (CDL for y = max(u))"
  parameter Integer nin(
    min=0)=0
    "Size of input array";
  Buildings.Controls.OBC.CDL.Interfaces.IntegerInput u[nin]
    "Integer input signal";
  Buildings.Controls.OBC.CDL.Interfaces.IntegerOutput y
    "Integer output signal";
protected
  Buildings.Controls.OBC.CDL.Conversions.IntegerToReal intToRea[nin]
    "Exact: every Integer is a Real";
  Buildings.Controls.OBC.CDL.Reals.MultiMax maxRea(
    final nin=nin)
    "Maximum";
  Buildings.Controls.OBC.CDL.Conversions.RealToInteger reaToInt
    "Exact: the maximum is one of the Integer inputs";
equation
  connect(u, intToRea.u);
  connect(intToRea.y, maxRea.u);
  connect(maxRea.y, reaToInt.u);
  connect(reaToInt.y, y);
end MultiMaxInteger;
