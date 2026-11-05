// inspect label elements in ZIUM annotation families (read-only)
foreach (var fam in new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().Where(f => f.Name.StartsWith("ZIUM")).ToList()) Try(fam.Name, () => {
  var fd = d.EditFamily(fam); L.AppendLine("== " + fam.Name + " cat=" + fd.OwnerFamily.FamilyCategory?.Name);
  foreach (var e in new FilteredElementCollector(fd).WhereElementIsNotElementType().OfClass(typeof(TextElement)))
    L.AppendLine($"  {e.GetType().Name} id={e.Id} '{((TextElement)e).Text}' type={fd.GetElement(e.GetTypeId())?.Name}");
  foreach (var e in new FilteredElementCollector(fd).WhereElementIsNotElementType().OfCategory(BuiltInCategory.OST_TextNotes))
    L.AppendLine($"  [cat] {e.GetType().Name} id={e.Id} {e.Name}");
  foreach (var t in new FilteredElementCollector(fd).OfClass(typeof(TextElementType))) L.AppendLine($"  TT '{t.Name}' id={t.Id}");
  fd.Close(false); });
foreach (var v in new FilteredElementCollector(d).OfClass(typeof(FillPatternElement)).Cast<FillPatternElement>()) { var fp=v.GetFillPattern(); L.AppendLine($"fill {v.Name} {fp.Target} grids={fp.GridCount}"); }
foreach (var t in new FilteredElementCollector(d).OfClass(typeof(FilledRegionType)).Cast<FilledRegionType>()) L.AppendLine($"frt {t.Name} fg={d.GetElement(t.ForegroundPatternId)?.Name}");
