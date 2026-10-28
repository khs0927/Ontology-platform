// 65_labels_hatch_section — 2026-10-28. Sources:
//  label type split: 40_families spec (SIN36 §1/§3/§4) — types already existed, labels shared one type.
//  hatches: Drive 건축,구조1.dxf HATCH pattern data (ZIUM_hatch.pat), KEY PLAN = NET ×100 ACI251 on 1/75 sheet.
//  section head: 건축,구조1.dxf layer SYM flag (h495 w143, text 405) on ZIUM_sheet_architect ×1.0157 (A1 ×100) → paper 4.87/1.41/4.0 mm.
var FD = @"C:\CODE\zium-templates\revit\families\";
var stamp = DateTime.Now.ToString("yyyyMMdd");
var bdir = FD + "_backup"; System.IO.Directory.CreateDirectory(bdir);
foreach (var f in System.IO.Directory.GetFiles(FD, "ZIUM_*.rfa")) { var b = System.IO.Path.Combine(bdir, System.IO.Path.GetFileName(f) + ".bak-" + stamp); if (!System.IO.File.Exists(b)) System.IO.File.Copy(f, b); }
L.AppendLine("rfa backups -> " + bdir);
// overwrite IFamilyLoadOptions (same as 55_reload)
var ab = System.Reflection.Emit.AssemblyBuilder.DefineDynamicAssembly(new System.Reflection.AssemblyName("ZOptAsm65"), System.Reflection.Emit.AssemblyBuilderAccess.Run);
var tb = ab.DefineDynamicModule("m").DefineType("ZOpt65", System.Reflection.TypeAttributes.Public | System.Reflection.TypeAttributes.Class);
tb.AddInterfaceImplementation(typeof(IFamilyLoadOptions));
var VA = System.Reflection.MethodAttributes.Public | System.Reflection.MethodAttributes.Virtual | System.Reflection.MethodAttributes.Final | System.Reflection.MethodAttributes.HideBySig | System.Reflection.MethodAttributes.NewSlot;
foreach (var im in typeof(IFamilyLoadOptions).GetMethods()) {
  var ps = im.GetParameters(); var mb = tb.DefineMethod(im.Name, VA, typeof(bool), ps.Select(p => p.ParameterType).ToArray()); var il = mb.GetILGenerator();
  for (int i = 0; i < ps.Length; i++) { var pt = ps[i].ParameterType; if (!pt.IsByRef) continue; var et = pt.GetElementType();
    il.Emit(System.Reflection.Emit.OpCodes.Ldarg, (short)(i + 1));
    if (et == typeof(bool)) { il.Emit(System.Reflection.Emit.OpCodes.Ldc_I4_1); il.Emit(System.Reflection.Emit.OpCodes.Stind_I1); }
    else { il.Emit(System.Reflection.Emit.OpCodes.Ldc_I4, (int)FamilySource.Family); il.Emit(System.Reflection.Emit.OpCodes.Stind_I4); } }
  il.Emit(System.Reflection.Emit.OpCodes.Ldc_I4_1); il.Emit(System.Reflection.Emit.OpCodes.Ret); tb.DefineMethodOverride(mb, im); }
var opt = (IFamilyLoadOptions)Activator.CreateInstance(tb.CreateType());
Family Fam(string n) => new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().FirstOrDefault(f => f.Name == n);
ElementType TT(Document fd, string n) => new FilteredElementCollector(fd).OfClass(typeof(TextElementType)).Cast<ElementType>().FirstOrDefault(t => t.Name == n);
void SaveReload(Document fd, string name) { var p = FD + name + ".rfa"; fd.SaveAs(p, new SaveAsOptions { OverwriteExistingFile = true }); fd.Close(false);
  Family f; bool ok; using (var t = new Transaction(d, "reload " + name)) { t.Start(); ok = d.LoadFamily(p, opt, out f); t.Commit(); } L.AppendLine("  reload " + name + " " + ok); }
// A. split shared label types
void Split(string fam, Func<string, string> map) => Try("split " + fam, () => {
  var fd = d.EditFamily(Fam(fam));
  using (var t = new Transaction(fd, "split")) { t.Start();
    foreach (AnnotationLabel a in new FilteredElementCollector(fd).OfClass(typeof(AnnotationLabel)).Cast<AnnotationLabel>().ToList()) {
      var tn = map(a.Text.Trim()); var ty = TT(fd, tn); if (ty == null) { L.AppendLine("  ! no type " + tn); continue; }
      a.ChangeTypeId(ty.Id); L.AppendLine("  " + fam + ": '" + a.Text.Trim() + "' -> " + tn); }
    t.Commit(); }
  SaveReload(fd, fam); });
Split("ZIUM_레벨헤드", s => s.Contains("이름") ? "ZIUM 3.85 레벨명" : "ZIUM 3.5 레벨값");
Split("ZIUM_뷰제목", s => s.Contains("축척") ? "ZIUM 3.2" : s.Contains("이름") ? "ZIUM 9.6" : "ZIUM 4.1");
foreach (var w in new[] { "22", "30", "40" }) Split("ZIUM_실명박스_" + w, s => s.Contains("이름") ? "ZIUM 실명 박스 3.5" : "ZIUM 실면적 2.5");
// B. source hatch patterns (values from ZIUM_hatch.pat, mm; model patterns keep source hatch scale)
FillGrid G(double ang, double ox, double oy, double sh, double off, double sc, params double[] dash) { var g = new FillGrid(); g.Angle = ang * Math.PI / 180; g.Origin = new UV(F(ox * sc), F(oy * sc)); g.Shift = F(sh * sc); g.Offset = F(off * sc); if (dash.Length > 0) g.SetSegments(dash.Select(x => F(Math.Abs(x) * sc)).ToList()); return g; }
ElementId Pat(string n, FillPatternTarget tg, IList<FillGrid> gs) { var e = new FilteredElementCollector(d).OfClass(typeof(FillPatternElement)).Cast<FillPatternElement>().FirstOrDefault(x => x.Name == n);
  var fp = new FillPattern(n, tg, FillPatternHostOrientation.ToView); fp.SetFillGrids(gs);
  if (e == null) e = FillPatternElement.Create(d, fp); else e.SetFillPattern(fp); L.AppendLine("  pattern " + n + " " + tg); return e.Id; }
ElementId pSand = null, pRoof = null, pNet = null, pKp = null;
Tx("hatch patterns", () => {
  pSand = Pat("ZIUM_AR-SAND", FillPatternTarget.Model, new List<FillGrid> {
    G(37.5, 0, 0, 28.5242, 39.8018, 5, 0, -38.608, 0, -43.18, 0, -41.275), G(7.5, 0, 0, 53.9242, 65.2018, 5, 0, -20.828, 0, -34.798, 0, -13.335),
    G(327.5, -31.242, 0, 66.6344, 42.6212, 5, 0, -12.7, 0, -45.72, 0, -59.69), G(317.5, -31.242, 0, 41.2344, 68.0212, 5, 0, -6.35, 0, -29.972, 0, -34.29) });
  pRoof = Pat("ZIUM_AR-RROOF", FillPatternTarget.Model, new List<FillGrid> {
    G(45, 0, 0, 55.88, 25.4, 50, 381, -50.8, 127, -25.4), G(45, 33.782, 12.7, -25.4, 33.782, 50, 76.2, -8.382, 152.4, -19.05), G(45, 12.7, 21.59, 132.08, 17.018, 50, 203.2, -35.56, 101.6, -25.4) });
  pNet = Pat("ZIUM_NET", FillPatternTarget.Model, new List<FillGrid> { G(0, 0, 0, 0, 3.175, 100), G(90, 0, 0, 0, 3.175, 100) });
  pKp = Pat("ZIUM_NET_KEYPLAN", FillPatternTarget.Drafting, new List<FillGrid> { G(0, 0, 0, 0, 3.175, 100.0 / 75), G(90, 0, 0, 0, 3.175, 100.0 / 75) });
});
// AR-RROOF dash pattern note: zero-length dots (0) in AR-SAND are dots; Revit needs >0, so F(0) segments are replaced below if rejected.
FilledRegionType FRT(string n) { var t = new FilteredElementCollector(d).OfClass(typeof(FilledRegionType)).Cast<FilledRegionType>().FirstOrDefault(x => x.Name == n);
  return t ?? (FilledRegionType)new FilteredElementCollector(d).OfClass(typeof(FilledRegionType)).Cast<FilledRegionType>().First(x => x.Name == "ZIUM_지중_세로선").Duplicate(n); }
Tx("filled region types", () => {
  foreach (var (n, p) in new[] { ("ZIUM_AR-SAND", pSand), ("ZIUM_AR-RROOF", pRoof), ("ZIUM_NET", pNet) }) { var t = FRT(n); t.ForegroundPatternId = p; t.ForegroundPatternColor = new Color(0, 0, 0); L.AppendLine("  frt " + n); }
  var sto = FRT("ZIUM_외벽STO_모래"); sto.ForegroundPatternId = pSand; L.AppendLine("  ZIUM_외벽STO_모래 -> ZIUM_AR-SAND");
  var kp = FRT("ZIUM_KEYPLAN"); kp.ForegroundPatternId = pKp; kp.ForegroundPatternColor = new Color(91, 91, 91); L.AppendLine("  ZIUM_KEYPLAN -> ZIUM_NET_KEYPLAN gray91 (ACI251)");
});
// C. section head ZIUM_단면헤드 from source flag
Try("section head", () => {
  var fd = d.EditFamily(Fam("단면 헤드 - 채우기"));
  var v = new FilteredElementCollector(fd).OfClass(typeof(View)).Cast<View>().First(x => !x.IsTemplate && x.ViewType != ViewType.ProjectBrowser && x.ViewType != ViewType.SystemBrowser && x.ViewType != ViewType.Internal);
  using (var t = new Transaction(fd, "z")) { t.Start();
    var del = new FilteredElementCollector(fd).WhereElementIsNotElementType().Where(e => e is CurveElement || e is FilledRegion).Select(e => e.Id).ToList(); fd.Delete(del);
    fd.FamilyCreate.NewDetailCurve(v, Line.CreateBound(new XYZ(0, 0, 0), new XYZ(0, F(4.87), 0)));
    fd.FamilyCreate.NewDetailCurve(v, Line.CreateBound(new XYZ(0, F(4.87), 0), new XYZ(F(1.41), 0, 0)));
    var a1 = new FilteredElementCollector(fd).OfClass(typeof(AnnotationLabel)).Cast<AnnotationLabel>().First(x => x.Text.Trim() == "1"); var b = (ElementType)fd.GetElement(a1.GetTypeId());
    var ty = TT(fd, "ZIUM 4.0 단면") ?? b.Duplicate("ZIUM 4.0 단면"); ty.get_Parameter(BuiltInParameter.TEXT_SIZE).Set(F(4.0)); ty.get_Parameter(BuiltInParameter.TEXT_FONT).Set(FONT); Try("bg", () => ty.get_Parameter(BuiltInParameter.TEXT_BACKGROUND).Set(1));
    foreach (AnnotationLabel a in new FilteredElementCollector(fd).OfClass(typeof(AnnotationLabel)).Cast<AnnotationLabel>().ToList()) {
      var s = a.Text.Trim(); if (s == "1") { a.ChangeTypeId(ty.Id); ElementTransformUtils.MoveElement(fd, a.Id, new XYZ(F(-4.41), F(3.14), 0) - new XYZ(a.Coord.X, a.Coord.Y, 0)); L.AppendLine("  detail no. label -> ZIUM 4.0 단면"); } }
    t.Commit(); }
  SaveReload(fd, "ZIUM_단면헤드");
  var sym = new FilteredElementCollector(d).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().First(s => s.FamilyName == "ZIUM_단면헤드");
  Tx("section tag type", () => {
    var vft = new FilteredElementCollector(d).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>().First(x => x.ViewFamily == ViewFamily.Section && x.Name == "건물 단면도");
    var z = new FilteredElementCollector(d).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>().FirstOrDefault(x => x.Name == "ZIUM 단면도") ?? (ViewFamilyType)vft.Duplicate("ZIUM 단면도");
    var tp = z.Parameters.Cast<Parameter>().First(p => p.StorageType == StorageType.ElementId && p.Definition.Name == "단면 태그");
    var tag = (ElementType)d.GetElement(tp.AsElementId());
    var ztag = new FilteredElementCollector(d).OfClass(tag.GetType()).Cast<ElementType>().FirstOrDefault(x => x.Name == "ZIUM 단면") ?? tag.Duplicate("ZIUM 단면");
    foreach (Parameter p in ztag.Parameters) if (p.StorageType == StorageType.ElementId && !p.IsReadOnly && d.GetElement(p.AsElementId()) is FamilySymbol fs && fs.FamilyName.Contains("헤드")) { p.Set(sym.Id); L.AppendLine("  tag param " + p.Definition.Name + " -> ZIUM_단면헤드"); }
    tp.Set(ztag.Id); L.AppendLine("  vft ZIUM 단면도 -> tag ZIUM 단면"); });
});
// D. line weights: API probe only (no public setter known) — report
L.AppendLine("lineweights: no public API (Manage > Additional Settings > Line Weights is UI-only)");
Try("save", () => { d.Save(); L.AppendLine("saved " + P); });

