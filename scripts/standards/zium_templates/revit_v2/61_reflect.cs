var ty = typeof(AnnotationLabelParameterFormatting);
foreach (var m in ty.GetMethods()) if (m.DeclaringType == ty) L.AppendLine("M " + m.ToString());
foreach (var c in ty.GetConstructors()) L.AppendLine("C " + c.ToString());
var fam = new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().First(f => f.Name == "ZIUM_레벨헤드");
var fd = d.EditFamily(fam);
foreach (AnnotationLabel a in new FilteredElementCollector(fd).OfClass(typeof(AnnotationLabel)))
  foreach (var f in a.GetParameterFormatting())
    foreach (var p in ty.GetProperties()) Try("p", () => L.AppendLine("lbl " + a.Id + " " + p.Name + "=" + p.GetValue(f)));
fd.Close(false);
