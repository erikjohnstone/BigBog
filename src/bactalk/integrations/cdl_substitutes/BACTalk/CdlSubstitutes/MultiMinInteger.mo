within BACTalk.CdlSubstitutes;
block MultiMinInteger
  "Output the minimum element of the input vector (CDL for y = min(u))"
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
  Buildings.Controls.OBC.CDL.Reals.MultiMin minRea(
    final nin=nin)
    "Minimum";
  Buildings.Controls.OBC.CDL.Conversions.RealToInteger reaToInt
    "Exact: the minimum is one of the Integer inputs";
equation
  connect(u, intToRea.u);
  connect(intToRea.y, minRea.u);
  connect(minRea.y, reaToInt.u);
  connect(reaToInt.y, y);
end MultiMinInteger;
