// ---- annotation families (geometry from ZIUM_GUIDE 7-5 / SIN36 §1·§3·§4, north arrow from 지음시트 block A$C269546BF) ----
const string FD = @"C:\CODE\zium-templates\revit\families"; System.IO.Directory.CreateDirectory(FD);
XYZ M(double x, double y) => new XYZ(F(x), F(y), 0);
View FV(Document fd) => new FilteredElementCollector(fd).OfClass(typeof(View)).Cast<View>().First(v => !v.IsTemplate && v.ViewType != ViewType.ProjectBrowser && v.ViewType != ViewType.SystemBrowser && v.ViewType != ViewType.Internal);
TextElementType TET(Document fd, string n, double mm, bool bold = false, int color = 0) { var b = new FilteredElementCollector(fd).OfClass(typeof(TextElementType)).Cast<TextElementType>().First();
  var t = new FilteredElementCollector(fd).OfClass(typeof(TextElementType)).Cast<TextElementType>().FirstOrDefault(x => x.Name == n) ?? (TextElementType)b.Duplicate(n);
  t.get_Parameter(BuiltInParameter.TEXT_SIZE).Set(F(mm)); t.get_Parameter(BuiltInParameter.TEXT_FONT).Set(FONT); Try("tb", () => t.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD).Set(bold ? 1 : 0));
  Try("tc", () => t.get_Parameter(BuiltInParameter.LINE_COLOR).Set(color)); Try("tbg", () => t.get_Parameter(BuiltInParameter.TEXT_BACKGROUND).Set(1)); return t; }
void Circ(Document fd, View v, XYZ c, double rmm) { fd.FamilyCreate.NewDetailCurve(v, Arc.Create(c, F(rmm), 0, Math.PI, XYZ.BasisX, XYZ.BasisY)); fd.FamilyCreate.NewDetailCurve(v, Arc.Create(c, F(rmm), Math.PI, 2 * Math.PI, XYZ.BasisX, XYZ.BasisY)); }
void Ln(Document fd, View v, XYZ a, XYZ b) { fd.FamilyCreate.NewDetailCurve(v, Line.CreateBound(a, b)); }
void Fill(Document fd, View v, IList<XYZ> pts) { var frt = new FilteredElementCollector(fd).OfClass(typeof(FilledRegionType)).Cast<FilledRegionType>().FirstOrDefault(); if (frt == null) { L.AppendLine("  ! no FilledRegionType in family"); return; }
  var loop = new CurveLoop(); for (int i = 0; i < pts.Count; i++) loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % pts.Count])); FilledRegion.Create(fd, frt.Id, v.Id, new List<CurveLoop> { loop }); }
Family Save(Document fd, string name) { var p = System.IO.Path.Combine(FD, name + ".rfa"); fd.SaveAs(p, new SaveAsOptions { OverwriteExistingFile = true }); fd.Close(false);
  Family f = new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().FirstOrDefault(x => x.Name == name);
  if (f == null) using (var t = new Transaction(d, "load " + name)) { t.Start(); d.LoadFamily(p, out f); t.Commit(); }
  L.AppendLine($"  family {name} -> {(f != null ? "loaded" : "NOT loaded")} {p}"); return f; }
Document EditCopy(string fam) => d.EditFamily(new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().First(f => f.Name == fam));
void DelAll(Document fd, Func<Element, bool> pred) { var ids = new FilteredElementCollector(fd).WhereElementIsNotElementType().Where(pred).Select(e => e.Id).ToList(); if (ids.Count > 0) fd.Delete(ids); }
const int GREEN = 65280, MAGENTA = 16711935; // ACI3 / ACI6 as Revit color ints (R + G*256 + B*65536)

// A. grid head: bubble Ø8.64 mm (ZIUM 7-5: 648 @ 1/75), number ZIUM 3.85 (SIN36 §4)
Try("grid head", () => { var fd = EditCopy("그리드 헤드 - 원"); var v = FV(fd);
  using (var t = new Transaction(fd, "z")) { t.Start(); DelAll(fd, e => e is CurveElement); Circ(fd, v, XYZ.Zero, 4.32);
    var tt = TET(fd, "ZIUM 3.85", 3.85); foreach (var lb in new FilteredElementCollector(fd).OfClass(typeof(TextElement)).ToElements()) lb.ChangeTypeId(tt.Id); t.Commit(); }
  Save(fd, "ZIUM_그리드헤드"); });
// B. level head: ▽ 4.0 × 3.47 mm (ZIUM 7-1/7-5: 300×260 @ 1/75), name ZIUM 3.85 green, value ZIUM 3.5 magenta (SIN36 §4)
Try("level head", () => { var fd = EditCopy("레벨 헤드 - 원"); var v = FV(fd);
  using (var t = new Transaction(fd, "z")) { t.Start(); DelAll(fd, e => e is CurveElement || e is FilledRegion);
    Ln(fd, v, M(0, 0), M(-2.0, 3.47)); Ln(fd, v, M(-2.0, 3.47), M(2.0, 3.47)); Ln(fd, v, M(2.0, 3.47), M(0, 0));
    var tn = TET(fd, "ZIUM 3.85 레벨명", 3.85, false, GREEN); var tv = TET(fd, "ZIUM 3.5 레벨값", 3.5, false, MAGENTA);
    foreach (TextElement lb in new FilteredElementCollector(fd).OfClass(typeof(TextElement)).Cast<TextElement>().ToList()) {
      bool isName = lb.Text.Contains("이름"); lb.ChangeTypeId(isName ? tn.Id : tv.Id);
      // name above value, both left of ▽ (SIN36 §4: ▽ 위 왼쪽, 2줄)
      var target = isName ? M(-3.0, 6.0) : M(-3.0, 1.5); ElementTransformUtils.MoveElement(fd, lb.Id, target - new XYZ(lb.Coord.X, lb.Coord.Y, 0)); }
    t.Commit(); }
  Save(fd, "ZIUM_레벨헤드"); });
// C. view title: number circle r12.8 + horizontal line (SIN36 §1), number ZIUM 4.1, name ZIUM 9.6 bold, scale ZIUM 3.2
Try("view title", () => { var fd = EditCopy("뷰 제목"); var v = FV(fd);
  using (var t = new Transaction(fd, "z")) { t.Start(); DelAll(fd, e => e is CurveElement);
    var c = M(-13.3, 0); Circ(fd, v, c, 12.8); Ln(fd, v, M(-26.1, 0), M(0.5, 0));
    var tNo = TET(fd, "ZIUM 4.1", 4.13); var tNm = TET(fd, "ZIUM 9.6", 9.6, true); var tSc = TET(fd, "ZIUM 3.2", 3.2);
    foreach (TextElement lb in new FilteredElementCollector(fd).OfClass(typeof(TextElement)).Cast<TextElement>().ToList()) {
      if (lb.Text.Contains("축척")) { lb.ChangeTypeId(tSc.Id); ElementTransformUtils.MoveElement(fd, lb.Id, M(3.0, -6.0) - new XYZ(lb.Coord.X, lb.Coord.Y, 0)); }
      else if (lb.Text.Contains("이름")) { lb.ChangeTypeId(tNm.Id); ElementTransformUtils.MoveElement(fd, lb.Id, M(3.0, 1.0) - new XYZ(lb.Coord.X, lb.Coord.Y, 0)); }
      else { lb.ChangeTypeId(tNo.Id); ElementTransformUtils.MoveElement(fd, lb.Id, M(-13.3, 4.5) - new XYZ(lb.Coord.X, lb.Coord.Y, 0)); } }
    t.Commit(); }
  Save(fd, "ZIUM_뷰제목"); });
// D. room tag box: 3 widths 22/30/40 mm × 11 mm, name 3.5 / area 2.5 (SIN36 §3)
foreach (var w in new[] { 22.0, 30.0, 40.0 }) Try("room tag " + w, () => { var fd = EditCopy("룸 태그"); var v = FV(fd);
  using (var t = new Transaction(fd, "z")) { t.Start();
    double hw = w / 2, hh = 5.5; Ln(fd, v, M(-hw, -hh), M(hw, -hh)); Ln(fd, v, M(hw, -hh), M(hw, hh)); Ln(fd, v, M(hw, hh), M(-hw, hh)); Ln(fd, v, M(-hw, hh), M(-hw, -hh));
    var tn = TET(fd, "ZIUM 실명 박스 3.5", 3.5); var ta = TET(fd, "ZIUM 실면적 2.5", 2.5);
    foreach (TextElement lb in new FilteredElementCollector(fd).OfClass(typeof(TextElement)).Cast<TextElement>().ToList()) lb.ChangeTypeId(lb.Text.Contains("이름") || lb.Text.Contains("룸") ? tn.Id : ta.Id);
    t.Commit(); }
  Save(fd, "ZIUM_실명박스_" + w); });
// E. north arrow (filled) as generic annotation: block A$C269546BF / 100 (sheet 84000 -> 840 mm)
Try("north arrow", () => { var fd = A.NewFamilyDocument(@"D:\ProgramData\Autodesk\RVT 2027\Family Templates\Korean\주석\미터법 일반 주석.rft"); var v = FV(fd);
  using (var t = new Transaction(fd, "z")) { t.Start(); DelAll(fd, e => e is TextElement);
    Circ(fd, v, XYZ.Zero, 6.0); Ln(fd, v, M(-6, 0), M(6, 0)); Ln(fd, v, M(0, 0), M(0, -6));
    Fill(fd, v, new[] { M(-0.4286, 0), M(0.4286, 0), M(0.4286, 6), M(-0.4286, 6) });
    var n = new double[,] { { 142.9, 936.9 }, { 57.1, 936.9 }, { 57.1, 731.2 }, { -57.1, 936.9 }, { -142.9, 936.9 }, { -142.9, 651.2 }, { -57.1, 651.2 }, { -57.1, 862.1 }, { 60.0, 651.2 }, { 142.9, 651.2 } };
    var pts = new List<XYZ>(); for (int i = 0; i < n.GetLength(0); i++) pts.Add(M(n[i, 0] / 100, n[i, 1] / 100)); Fill(fd, v, pts); t.Commit(); }
  Save(fd, "ZIUM_방위표"); });
// F. project types that use the families
Tx("types using families", () => {
  FamilySymbol Sym(string fam) { var s = new FilteredElementCollector(d).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().FirstOrDefault(x => x.FamilyName == fam); if (s != null && !s.IsActive) s.Activate(); return s; }
  var gs = Sym("ZIUM_그리드헤드"); if (gs != null) { var bg = ByName<GridType>("6.5mm 버블"); var g = ByName<GridType>("ZIUM 그리드") ?? (GridType)bg.Duplicate("ZIUM 그리드");
    g.get_Parameter(BuiltInParameter.GRID_HEAD_TAG).Set(gs.Id); Try("bubble end", () => { g.get_Parameter(BuiltInParameter.GRID_BUBBLE_END_1).Set(1); g.get_Parameter(BuiltInParameter.GRID_BUBBLE_END_2).Set(0); }); }
  var ls = Sym("ZIUM_레벨헤드"); if (ls != null) { var bl = new FilteredElementCollector(d).OfClass(typeof(LevelType)).Cast<LevelType>().First(); var lt = ByName<LevelType>("ZIUM 레벨") ?? (LevelType)bl.Duplicate("ZIUM 레벨");
    lt.get_Parameter(BuiltInParameter.LEVEL_HEAD_TAG).Set(ls.Id); Try("lv color", () => lt.get_Parameter(BuiltInParameter.LINE_COLOR).Set(255));
    foreach (Level l in new FilteredElementCollector(d).OfClass(typeof(Level))) Try("lv type", () => l.ChangeTypeId(lt.Id)); }
  var vs = Sym("ZIUM_뷰제목"); var vp = ET("뷰포트", "제목 선 없음"); if (vs != null && vp != null) { var z = ET("뷰포트", "ZIUM 뷰제목") ?? vp.Duplicate("ZIUM 뷰제목"); Try("vp tag", () => z.get_Parameter(BuiltInParameter.VIEWPORT_ATTR_LABEL_TAG).Set(vs.Id)); Try("vp line", () => z.get_Parameter(BuiltInParameter.VIEWPORT_ATTR_SHOW_EXTENSION_LINE).Set(0)); }
});
