within BACTalk.CdlSubstitutes;
block TrueArrayConditional
  "Output a Boolean array with a given number of true elements and a priority order (CDL for the algorithm)"
  parameter Integer nin(
    min=0)=0
    "Size of input array";
  parameter Integer nout(
    min=0)=nin
    "Size of output array";
  Buildings.Controls.OBC.CDL.Interfaces.IntegerInput u
    "Number of true elements";
  Buildings.Controls.OBC.CDL.Interfaces.IntegerInput uIdx[nin]
    "Array of indices by order of priority to be true";
  Buildings.Controls.OBC.CDL.Interfaces.BooleanOutput y1[nout]
    "Output";
protected
  Buildings.Controls.OBC.CDL.Integers.GreaterEqualThreshold aboMin[nin](
    each final t=1)
    "Index at least 1";
  Buildings.Controls.OBC.CDL.Integers.LessEqualThreshold belMax[nin](
    each final t=nout)
    "Index at most nout";
  Buildings.Controls.OBC.CDL.Logical.And val[nin]
    "Position holds a valid index";
  Buildings.Controls.OBC.CDL.Routing.BooleanVectorReplicator repVal(
    final nin=nin,
    final nout=nin)
    "Validity of every position, once per position";
  Buildings.Controls.OBC.CDL.Logical.Sources.Constant upTo[nin, nin](
    final k={j <= i for j in 1:nin, i in 1:nin})
    "Row i keeps the positions up to i";
  Buildings.Controls.OBC.CDL.Logical.And valUpTo[nin, nin]
    "Valid positions up to i";
  Buildings.Controls.OBC.CDL.Conversions.BooleanToInteger valUpToInt[nin, nin]
    "Valid positions up to i, as 1 or 0";
  Buildings.Controls.OBC.CDL.Integers.MultiSum cou[nin](
    each final nin=nin)
    "Number of valid positions up to and including i (the loop's iTru after i)";
  Buildings.Controls.OBC.CDL.Routing.IntegerScalarReplicator repU(
    final nout=nin)
    "Number of true elements, once per position";
  Buildings.Controls.OBC.CDL.Integers.LessEqual fit[nin]
    "The loop has not yet set u elements when it reaches position i";
  Buildings.Controls.OBC.CDL.Logical.And tak[nin]
    "Position i sets its index true";
  Buildings.Controls.OBC.CDL.Routing.IntegerVectorReplicator repIdx(
    final nin=nin,
    final nout=nout)
    "Indices, once per output";
  Buildings.Controls.OBC.CDL.Integers.GreaterEqualThreshold aboOut[nout, nin](
    final t={k for i in 1:nin, k in 1:nout})
    "uIdx[i] >= k";
  Buildings.Controls.OBC.CDL.Integers.LessEqualThreshold belOut[nout, nin](
    final t={k for i in 1:nin, k in 1:nout})
    "uIdx[i] <= k";
  Buildings.Controls.OBC.CDL.Logical.And isOut[nout, nin]
    "uIdx[i] == k";
  Buildings.Controls.OBC.CDL.Routing.BooleanVectorReplicator repTak(
    final nin=nin,
    final nout=nout)
    "Taken positions, once per output";
  Buildings.Controls.OBC.CDL.Logical.And sel[nout, nin]
    "Position i sets output k";
  Buildings.Controls.OBC.CDL.Logical.MultiOr anySel[nout](
    each final nin=nin)
    "Some position sets output k";
equation
  connect(uIdx, aboMin.u);
  connect(uIdx, belMax.u);
  connect(aboMin.y, val.u1);
  connect(belMax.y, val.u2);
  connect(val.y, repVal.u);
  connect(repVal.y, valUpTo.u1);
  connect(upTo.y, valUpTo.u2);
  connect(valUpTo.y, valUpToInt.u);
  connect(valUpToInt.y, cou.u);
  connect(u, repU.u);
  connect(cou.y, fit.u1);
  connect(repU.y, fit.u2);
  connect(val.y, tak.u1);
  connect(fit.y, tak.u2);
  connect(uIdx, repIdx.u);
  connect(repIdx.y, aboOut.u);
  connect(repIdx.y, belOut.u);
  connect(aboOut.y, isOut.u1);
  connect(belOut.y, isOut.u2);
  connect(tak.y, repTak.u);
  connect(repTak.y, sel.u1);
  connect(isOut.y, sel.u2);
  connect(sel.y, anySel.u);
  connect(anySel.y, y1);
end TrueArrayConditional;
