within BACTalk.CdlSubstitutes;
block TimerWithReset
  "Timer measuring the time since the Boolean input became true or the reset rose (CDL for the when-equations)"
  parameter Real t(
    final quantity="Time",
    final unit="s")=0
    "Threshold time for comparison";
  Buildings.Controls.OBC.CDL.Interfaces.BooleanInput u
    "Input that switches timer on if true, and off if false";
  Buildings.Controls.OBC.CDL.Interfaces.BooleanInput reset
    "Reset signal";
  Buildings.Controls.OBC.CDL.Interfaces.RealOutput y(
    final quantity="Time",
    final unit="s")
    "Elapsed time";
  Buildings.Controls.OBC.CDL.Interfaces.BooleanOutput passed
    "True if the elapsed time is greater than threshold";
protected
  Buildings.Controls.OBC.CDL.Logical.Edge risU
    "u rises";
  Buildings.Controls.OBC.CDL.Logical.Edge risRes
    "reset rises";
  Buildings.Controls.OBC.CDL.Logical.Or res
    "Restart: when {u, reset}";
  Buildings.Controls.OBC.CDL.Logical.Pre preTog
    "Toggle at the previous evaluation";
  Buildings.Controls.OBC.CDL.Logical.Xor tog
    "Flips on every restart, so two restarts on consecutive evaluations are both edges";
  Buildings.Controls.OBC.CDL.Logical.Not notTog
    "Inverted toggle";
  Buildings.Controls.OBC.CDL.Logical.TimerAccumulating timRis
    "Time accumulated while u since the toggle last rose";
  Buildings.Controls.OBC.CDL.Logical.TimerAccumulating timFal
    "Time accumulated while u since the toggle last fell";
  Buildings.Controls.OBC.CDL.Reals.Switch cur
    "The timer the last restart cleared";
  Buildings.Controls.OBC.CDL.Reals.Sources.Constant zer(
    final k=0)
    "Zero";
  Buildings.Controls.OBC.CDL.Reals.Switch ela
    "y = if u then time - entryTime else 0";
  Buildings.Controls.OBC.CDL.Reals.LessThreshold notYet(
    final t=t)
    "Elapsed time below the threshold";
  Buildings.Controls.OBC.CDL.Logical.Not rea
    "Elapsed time at or above the threshold";
  Buildings.Controls.OBC.CDL.Logical.And pasOn
    "passed while u: u and elapsed time >= t";
  Buildings.Controls.OBC.CDL.Logical.FallingEdge falU
    "u falls";
  Buildings.Controls.OBC.CDL.Logical.Or anyEve
    "Any when-clause event: u rises, reset rises or u falls";
  Buildings.Controls.OBC.CDL.Logical.Sources.Constant tru(
    final k=true)
    "True";
  Buildings.Controls.OBC.CDL.Logical.Pre notIni
    "False at initialization only";
  Buildings.Controls.OBC.CDL.Logical.And eveAftIni
    "An event after initialization (a when-clause does not fire at initialization)";
  Buildings.Controls.OBC.CDL.Logical.Sources.Constant fal(
    final k=false)
    "False";
  Buildings.Controls.OBC.CDL.Logical.Latch see
    "True once any event has occurred";
  Buildings.Controls.OBC.CDL.Logical.Not noEve
    "No event yet";
  Buildings.Controls.OBC.CDL.Reals.Sources.Constant thr(
    final k=t)
    "Threshold";
  Buildings.Controls.OBC.CDL.Reals.GreaterThreshold pos(
    final t=0)
    "Threshold above zero";
  Buildings.Controls.OBC.CDL.Logical.Not nonPos
    "Threshold at or below zero";
  Buildings.Controls.OBC.CDL.Logical.And pasIni
    "passed = t <= 0 from the initial equation until the first event";
  Buildings.Controls.OBC.CDL.Logical.Or pas
    "passed";
equation
  connect(u, risU.u);
  connect(reset, risRes.u);
  connect(risU.y, res.u1);
  connect(risRes.y, res.u2);
  connect(res.y, tog.u1);
  connect(preTog.y, tog.u2);
  connect(tog.y, preTog.u);
  connect(tog.y, notTog.u);
  connect(tog.y, timRis.reset);
  connect(notTog.y, timFal.reset);
  connect(u, timRis.u);
  connect(u, timFal.u);
  connect(tog.y, cur.u2);
  connect(timRis.y, cur.u1);
  connect(timFal.y, cur.u3);
  connect(u, ela.u2);
  connect(cur.y, ela.u1);
  connect(zer.y, ela.u3);
  connect(ela.y, y);
  connect(ela.y, notYet.u);
  connect(notYet.y, rea.u);
  connect(u, pasOn.u1);
  connect(rea.y, pasOn.u2);
  connect(u, falU.u);
  connect(res.y, anyEve.u1);
  connect(falU.y, anyEve.u2);
  connect(tru.y, notIni.u);
  connect(notIni.y, eveAftIni.u1);
  connect(anyEve.y, eveAftIni.u2);
  connect(eveAftIni.y, see.u);
  connect(fal.y, see.clr);
  connect(see.y, noEve.u);
  connect(noEve.y, pasIni.u1);
  connect(thr.y, pos.u);
  connect(pos.y, nonPos.u);
  connect(nonPos.y, pasIni.u2);
  connect(pasOn.y, pas.u1);
  connect(pasIni.y, pas.u2);
  connect(pas.y, passed);
end TimerWithReset;
