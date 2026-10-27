foreach (var fn in new[] { "그리드 헤드 - 원", "레벨 헤드 - 원", "뷰 제목", "단면 헤드 - 채우기" }) {
  var fam = new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().FirstOrDefault(f => f.Name == fn); if (fam == null) { L.AppendLine("no fam " + fn); continue; }
  var fd = d.EditFamily(fam); L.AppendLine("== " + fn);
  foreach (var e in new FilteredElementCollector(fd).WhereElementIsNotElementType()) {
    if (e is CurveElement ce) { var c = ce.GeometryCurve; L.AppendLine($"  {ce.GetType().Name} {c.GetType().Name} " + (c.IsBound ? $"{c.GetEndPoint(0).X*304.8:F2},{c.GetEndPoint(0).Y*304.8:F2} -> {c.GetEndPoint(1).X*304.8:F2},{c.GetEndPoint(1).Y*304.8:F2}" : "unbound") + (c is Arc a ? $" r={a.Radius*304.8:F2} c={a.Center.X*304.8:F2},{a.Center.Y*304.8:F2}" : "")); }
    else if (e is TextElement te) L.AppendLine($"  {te.GetType().Name} '{te.Text}' at {te.Coord.X*304.8:F2},{te.Coord.Y*304.8:F2} type={fd.GetElement(te.GetTypeId())?.Name}");
    else if (e is FilledRegion) L.AppendLine("  FilledRegion " + e.Id);
  }
  foreach (var t in new FilteredElementCollector(fd).OfClass(typeof(TextElementType))) L.AppendLine($"  TT '{t.Name}' size={(t.get_Parameter(BuiltInParameter.TEXT_SIZE)?.AsDouble()??0)*304.8:F2} font={t.get_Parameter(BuiltInParameter.TEXT_FONT)?.AsString()}");
  fd.Close(false); }
foreach (var fs in new FilteredElementCollector(d).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_RoomTags).Cast<FamilySymbol>()) L.AppendLine($"roomtag '{fs.FamilyName}'/'{fs.Name}'");
