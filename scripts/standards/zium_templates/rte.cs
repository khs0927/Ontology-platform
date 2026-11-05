var A = app.Application; var log = new System.Text.StringBuilder();
System.IO.Directory.CreateDirectory(@"C:\CODE\zium-templates\revit");
var tpl = A.DefaultProjectTemplate; log.Append("tpl="+tpl+"; ");
var d = A.NewProjectTemplateDocument(tpl);
using (var t = new Transaction(d, "ZIUM")) { t.Start();
  Family fam; bool ok = d.LoadFamily(@"C:\Users\khs09\Documents\revit_mcp\families\ZIUM_도곽_A1.rfa", out fam);
  log.Append("load="+ok+"; ");
  ElementId tb = ElementId.InvalidElementId;
  if (fam != null) foreach (var id in fam.GetFamilySymbolIds()) { tb = id; var s=(FamilySymbol)d.GetElement(id); if(!s.IsActive) s.Activate(); break; }
  if (tb != ElementId.InvalidElementId) {
    var sh = ViewSheet.Create(d, tb); sh.SheetNumber="A000"; sh.Name="표지 및 도면목록";
    var sh2 = ViewSheet.Create(d, tb); sh2.SheetNumber="A202"; sh2.Name="1층 평면도";
    log.Append("sheets=2; ");
  }
  t.Commit(); }
var o = new SaveAsOptions(); o.OverwriteExistingFile = true;
d.SaveAs(@"C:\CODE\zium-templates\revit\ZIUM_template.rte", o); d.Close(false); log.Append("saved rte; ");
try { var io = new Autodesk.Revit.DB.IFC.IFCImportOptions(); io.Intent = Autodesk.Revit.DB.IFC.IFCImportIntent.Reference;
  var di = A.OpenIFCDocument(@"C:\CODE\zium-templates\smoke\GOYEON1525_mass.ifc", io);
  int n = new FilteredElementCollector(di).WhereElementIsNotElementType().GetElementCount();
  di.SaveAs(@"C:\CODE\zium-templates\smoke\GOYEON1525_mass_ifc.rvt", o); di.Close(false); log.Append("ifc elements="+n+" saved rvt; ");
} catch (Exception e) { log.Append("ifc err "+e.Message); }
return log.ToString();
