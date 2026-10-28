var pp = typeof(AnnotationLabelParameterFormatting).GetProperty("Prefix", System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic);
L.AppendLine("Prefix CanWrite=" + pp.CanWrite + " nonpublic setter=" + (pp.GetSetMethod(true) != null));
var fam = new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().First(f => f.Name == "ZIUM_레벨헤드");
var fd = d.EditFamily(fam);
foreach (AnnotationLabel a in new FilteredElementCollector(fd).OfClass(typeof(AnnotationLabel)).Cast<AnnotationLabel>())
  foreach (var f in a.GetParameterFormatting()) L.AppendLine("  '" + a.Text.Trim() + "' param=" + f.GetParameterDefinition(fd)?.Name + " prefix='" + f.Prefix + "' suffix='" + f.Suffix + "' sample='" + f.SampleText + "'");
fd.Close(false);

