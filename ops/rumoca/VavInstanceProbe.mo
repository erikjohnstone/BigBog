model BACTalkModelicaJsonVavInstanceProbe
  Buildings.Controls.OBC.ASHRAE.G36.AHUs.MultiZone.VAV.Controller controller(
    eneStd=Buildings.Controls.OBC.ASHRAE.G36.Types.EnergyStandard.ASHRAE90_1,
    venStd=Buildings.Controls.OBC.ASHRAE.G36.Types.VentilationStandard.ASHRAE62_1)
    annotation (__cdl(isControls=true));
end BACTalkModelicaJsonVavInstanceProbe;
