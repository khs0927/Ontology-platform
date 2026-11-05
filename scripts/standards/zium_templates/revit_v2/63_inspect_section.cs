// inspect section head family + section tag types (read-only)
foreach (var fam in new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().Where(f => f.FamilyCategory != null && f.FamilyCategory.Id.Value == (long)BuiltInCategory.OST_SectionHeads).ToList()) {
  var fd = d.EditFamily(fam); L.AppendLine("== " + fam.Name);
  foreach (var e in new FilteredElementCollector(fd).WhereElementIsNotElementType()) {
    if (e is CurveElement ce && ce.GeometryCurve.IsBound) { var c = ce.GeometryCurve; L.AppendLine($"  {ce.GetType().Name} {c.GetEndPoint(0).X*304.8:F2},{c.GetEndPoint(0).Y*304.8:F2} -> {c.GetEndPoint(1).X*304.8:F2},{c.GetEndPoint(1).Y*304.8:F2}"); }
    else if (e is TextElement te) L.AppendLine($"  {te.GetType().Name} '{te.Text}' at {te.Coord.X*304.8:F2},{te.Coord.Y*304.8:F2} type={fd.GetElement(te.GetTypeId())?.Name}");
    else if (e is FilledRegion) L.AppendLine("  FilledRegion");
  }
  fd.Close(false); }
foreach (var t in new FilteredElementCollector(d).OfClass(typeof(ElementType)).Cast<ElementType>().Where(t => t.Category != null && t.Category.Id.Value == (long)BuiltInCategory.OST_SectionHeads)) {
  L.Append("tagtype " + t.GetType().Name + " fam='" + t.FamilyName + "' name='" + t.Name + "'");
  foreach (Parameter p in t.Parameters) if (p.StorageType == StorageType.ElementId) L.Append(" | " + p.Definition.Name + "=" + d.GetElement(p.AsElementId())?.Name);
  L.AppendLine(); }
foreach (var v in new FilteredElementCollector(d).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>().Where(v => v.ViewFamily == ViewFamily.Section)) {
  L.Append("vft " + v.Name); foreach (Parameter p in v.Parameters) if (p.StorageType == StorageType.ElementId) L.Append(" | " + p.Definition.Name + "=" + d.GetElement(p.AsElementId())?.Name); L.AppendLine(); }
