within BACTalk.CdlSubstitutes;
block Initialization
  "Force signal value at initial time (CDL for y = if initial() then yIni else u)"
  parameter Boolean yIni=false
    "Initial value";
  Buildings.Controls.OBC.CDL.Interfaces.BooleanInput u
    "Input";
  Buildings.Controls.OBC.CDL.Interfaces.BooleanOutput y
    "Output";
protected
  Buildings.Controls.OBC.CDL.Logical.Sources.Constant tru(
    final k=true)
    "True";
  Buildings.Controls.OBC.CDL.Logical.Pre notIni
    "False at initialization only";
  Buildings.Controls.OBC.CDL.Logical.Sources.Constant ini(
    final k=yIni)
    "Initial value";
  Buildings.Controls.OBC.CDL.Logical.Switch swi
    "The initial value at initialization, then the input";
equation
  connect(tru.y, notIni.u);
  connect(notIni.y, swi.u2);
  connect(u, swi.u1);
  connect(ini.y, swi.u3);
  connect(swi.y, y);
end Initialization;
