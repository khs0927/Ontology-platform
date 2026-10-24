// switch all text/dim/label types to NanumSquare. Backup first.
var bdir = @"C:\CODE\zium-templates\revit\_backup"; System.IO.Directory.CreateDirectory(bdir);
var bp = System.IO.Path.Combine(bdir, "ZIUM_template_v2_prefont_" + DateTime.Now.ToString("yyyyMMdd_HHmm") + ".rte");
if (!System.IO.File.Exists(bp)) System.IO.File.Copy(P, bp); L.AppendLine("backup " + bp);
int n = 0;
Tx("font project types", () => {
  foreach (var t in new FilteredElementCollector(d).OfClass(typeof(ElementType)).Cast<ElementType>()) {
    var p = t.get_Parameter(BuiltInParameter.TEXT_FONT); if (p != null && !p.IsReadOnly && p.AsString() != FONT) { p.Set(FONT); n++; } }
});
L.AppendLine("project types changed " + n);
foreach (var fam in new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().Where(f => f.Name.StartsWith("ZIUM")).ToList()) Try(fam.Name, () => {
  var fd = d.EditFamily(fam); int c = 0;
  using (var t = new Transaction(fd, "font")) { t.Start();
    foreach (var tt in new FilteredElementCollector(fd).OfClass(typeof(ElementType)).Cast<ElementType>()) {
      var p = tt.get_Parameter(BuiltInParameter.TEXT_FONT); if (p != null && !p.IsReadOnly && p.AsString() != FONT) { p.Set(FONT); c++; } }
    t.Commit(); }
  if (c > 0) { var fp = @"C:\CODE\zium-templates\revit\families\" + fam.Name + ".rfa";
    fd.SaveAs(fp, new SaveAsOptions { OverwriteExistingFile = true }); fd.LoadFamily(d); fd.Close(false); }
  else fd.Close(false);
  L.AppendLine("  fam " + fam.Name + " label types changed " + c);
});
// verify
var bad = new FilteredElementCollector(d).OfClass(typeof(ElementType)).Cast<ElementType>().Select(t => t.get_Parameter(BuiltInParameter.TEXT_FONT)?.AsString()).Where(s => s != null).GroupBy(s => s).Select(g => g.Key + "=" + g.Count());
L.AppendLine("fonts now: " + string.Join(", ", bad));
