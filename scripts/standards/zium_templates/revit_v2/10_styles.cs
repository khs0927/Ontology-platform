// ---- text types: revit-mcp-guideline 22_setup (16) + SIN36 §2 (2 new) ----
Tx("text types", () => {
  var baseT = ByName<TextNoteType>("2.5mm Arial"); var dot = ET("화살촉", "채워진 점 1.5mm");
  var specs = new (string n, double h, bool b, bool box)[] { ("ZIUM 2.5",2.5,false,false),("ZIUM 3",3,false,false),("ZIUM 3.2",3.2,false,false),("ZIUM 3.3",3.3,false,false),("ZIUM 3.5",3.5,false,false),("ZIUM 3.85",3.85,false,false),
    ("ZIUM 4.1",4.13,false,false),("ZIUM 4.4",4.4,true,false),("ZIUM 5",5,false,false),("ZIUM 5 굵게",5,true,false),("ZIUM 7 굵게",7,true,false),("ZIUM 9.6",9.6,true,false),("ZIUM 14 굵게",14,true,false),("ZIUM 24 굵게",24,true,false),
    ("ZIUM 실명 박스 3.5",3.5,false,true),("ZIUM 실명 4",4,false,false),("ZIUM 실면적 2.5",2.5,false,false),("ZIUM 실내레벨 2.5",2.5,false,false) };
  foreach (var s in specs) { var t = ByName<TextNoteType>(s.n) ?? (TextNoteType)baseT.Duplicate(s.n);
    t.get_Parameter(BuiltInParameter.TEXT_SIZE).Set(F(s.h)); t.get_Parameter(BuiltInParameter.TEXT_FONT).Set(FONT);
    Try("bg", () => t.get_Parameter(BuiltInParameter.TEXT_BACKGROUND).Set(1)); Try("bold", () => t.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD).Set(s.b ? 1 : 0));
    Try("box", () => t.get_Parameter(BuiltInParameter.TEXT_BOX_VISIBILITY).Set(s.box ? 1 : 0)); Try("w", () => t.get_Parameter(BuiltInParameter.TEXT_WIDTH_SCALE).Set(1.0));
    if (dot != null) Try("arrow", () => t.get_Parameter(BuiltInParameter.LEADER_ARROWHEAD).Set(dot.Id)); }
});
// ---- dimension types: SIN36 §2 (3mm, 3mm 상세: text 2.5, tick, witness gap 1.5) + YUJIN dim style 80 (text 2, _DOT, gap 1.5, ext 1, text gap 0.5) ----
Tx("dim types", () => {
  var tick = ET("화살촉", "대각선 3mm"); var dot = ET("화살촉", "채워진 점 1.5mm");
  var baseD = new FilteredElementCollector(d).OfClass(typeof(DimensionType)).Cast<DimensionType>().First(t => t.Name == "대각선 - 2.5mm Arial");
  void DT(string n, double txt, ElementType arrow, double gap, double ext, double tgap) {
    var t = ByName<DimensionType>(n) ?? (DimensionType)baseD.Duplicate(n);
    t.get_Parameter(BuiltInParameter.TEXT_SIZE).Set(F(txt)); t.get_Parameter(BuiltInParameter.TEXT_FONT).Set(FONT);
    if (arrow != null) Try(n + " arrow", () => t.get_Parameter(BuiltInParameter.DIM_LEADER_ARROWHEAD).Set(arrow.Id));
    Try(n + " gap", () => BP(t, new[]{"WITNS_LINE_GAP_TO_ELT","DIM_WITNS_LINE_GAP_TO_ELT"}, new[]{"치수보조선 간격","Witness Line Gap to Element"}).Set(F(gap)));
    if (ext > 0) Try(n + " ext", () => BP(t, new[]{"WITNS_LINE_EXTENSION","DIM_WITNS_LINE_EXTENSION"}, new[]{"치수보조선 연장","Witness Line Extension"}).Set(F(ext)));
    if (tgap > 0) Try(n + " tgap", () => t.get_Parameter(BuiltInParameter.TEXT_DIST_TO_LINE).Set(F(tgap)));
    Try(n + " bg", () => t.get_Parameter(BuiltInParameter.DIM_TEXT_BACKGROUND).Set(1)); }
  DT("ZIUM 치수 3mm", 2.5, tick, 1.5, 0, 0); DT("ZIUM 치수 3mm 상세", 2.5, tick, 1.5, 0, 0); DT("ZIUM 치수 80", 2.0, dot, 1.5, 1.0, 0.5);
});
// ---- line patterns + line styles: 22_setup (10) + SIN36 §5 (숨은선 2/1, 중심선 red dash-dot, 레벨선 red) ----
Tx("line styles", () => {
  if (LinePatternElement.GetLinePatternElementByName(d, "ZIUM_숨은선") == null) {
    var lp = new LinePattern("ZIUM_숨은선"); lp.SetSegments(new List<LinePatternSegment> { new LinePatternSegment(LinePatternSegmentType.Dash, F(2)), new LinePatternSegment(LinePatternSegmentType.Space, F(1)) });
    LinePatternElement.Create(d, lp); }
  var lines = LinesCat();
  void NewLS(string name, Color c, int w, string pat) { var sc = lines.SubCategories.Cast<Category>().FirstOrDefault(s => s.Name == name) ?? d.Settings.Categories.NewSubcategory(lines, name);
    sc.LineColor = c; sc.SetLineWeight(w, GraphicsStyleType.Projection);
    if (pat != null) { var lp = LinePatternElement.GetLinePatternElementByName(d, pat); if (lp != null) sc.SetLinePatternId(lp.Id, GraphicsStyleType.Projection); else L.AppendLine("  ! no pattern " + pat); } }
  var k = RGB(0,0,0);
  NewLS("ZIUM_TIT", k, 5, null); NewLS("ZIUM_TIT_가는선", k, 2, null); NewLS("ZIUM_표", k, 1, null); NewLS("ZIUM_표_굵은선", k, 4, null);
  NewLS("ZIUM_대지경계선", RGB(255,0,255), 4, "이중 대시"); NewLS("ZIUM_도로선", RGB(128,128,128), 2, "대시"); NewLS("ZIUM_주출입구", RGB(255,0,0), 6, null);
  NewLS("ZIUM_지반선", k, 8, null); NewLS("ZIUM_KEY", RGB(255,0,255), 3, null); NewLS("ZIUM_건축선", RGB(255,0,0), 2, "대시 점");
  NewLS("ZIUM_숨은선", k, 1, "ZIUM_숨은선"); NewLS("ZIUM_중심선", RGB(255,0,0), 1, "중심"); NewLS("ZIUM_레벨선", RGB(255,0,0), 1, null);
  NewLS("ZIUM_입면외곽", k, 5, null); NewLS("ZIUM_가는선", RGB(128,128,128), 1, null);
});
// ---- object styles: SIN36 §5 pen hierarchy ----
Tx("object styles", () => {
  var cats = d.Settings.Categories;
  void OS(BuiltInCategory b, int cut, int proj, Color c = null, string pat = null) { Category ca = null; try { ca = cats.get_Item(b); } catch { } if (ca == null) { L.AppendLine("  ! no cat " + b); return; }
    if (cut > 0) Try(b + " cut", () => ca.SetLineWeight(cut, GraphicsStyleType.Cut)); if (proj > 0) ca.SetLineWeight(proj, GraphicsStyleType.Projection);
    if (c != null) ca.LineColor = c; if (pat != null) { var lp = LinePatternElement.GetLinePatternElementByName(d, pat); if (lp != null) ca.SetLinePatternId(lp.Id, GraphicsStyleType.Projection); } }
  foreach (var b in new[] { BuiltInCategory.OST_Walls, BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_Columns, BuiltInCategory.OST_Floors, BuiltInCategory.OST_Roofs, BuiltInCategory.OST_StructuralFraming, BuiltInCategory.OST_StructuralFoundation }) OS(b, 6, 2);
  foreach (var b in new[] { BuiltInCategory.OST_Stairs, BuiltInCategory.OST_StairsRailing, BuiltInCategory.OST_Ceilings }) OS(b, 4, 2);
  foreach (var b in new[] { BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows, BuiltInCategory.OST_CurtainWallPanels, BuiltInCategory.OST_CurtainWallMullions }) OS(b, 4, 2);
  var g = RGB(128,128,128);
  foreach (var b in new[] { BuiltInCategory.OST_Furniture, BuiltInCategory.OST_FurnitureSystems, BuiltInCategory.OST_PlumbingFixtures, BuiltInCategory.OST_Casework, BuiltInCategory.OST_SpecialityEquipment, BuiltInCategory.OST_Planting }) OS(b, 0, 1, g);
  OS(BuiltInCategory.OST_Toposolid, 8, 5); OS(BuiltInCategory.OST_Dimensions, 0, 1, RGB(0,0,0));
  OS(BuiltInCategory.OST_Grids, 0, 1, RGB(255,0,0)); OS(BuiltInCategory.OST_Levels, 0, 1, RGB(255,0,0));
  // grid / level types (SIN36 §5 7·8)
  var gt = ByName<GridType>("6.5mm 버블"); var cen = LinePatternElement.GetLinePatternElementByName(d, "중심");
  if (gt != null) { Try("grid color", () => gt.get_Parameter(BuiltInParameter.GRID_CENTER_SEGMENT_COLOR).Set(255)); if (cen != null) Try("grid pat", () => gt.get_Parameter(BuiltInParameter.GRID_CENTER_SEGMENT_PATTERN).Set(cen.Id));
    Try("grid w", () => gt.get_Parameter(BuiltInParameter.GRID_CENTER_SEGMENT_WEIGHT).Set(1)); }
  foreach (LevelType lt in new FilteredElementCollector(d).OfClass(typeof(LevelType))) { Try("lv color", () => lt.get_Parameter(BuiltInParameter.LINE_COLOR).Set(255)); Try("lv pat", () => lt.get_Parameter(BuiltInParameter.LINE_PATTERN).Set(LinePatternElement.GetSolidPatternId())); Try("lv w", () => lt.get_Parameter(BuiltInParameter.LINE_PEN).Set(1)); }
});
// ---- fill patterns + filled region types: ZIUM_GUIDE hatch table -> SIN36 §6 ----
Tx("fills", () => {
  FillPatternElement FPE(string n, FillPatternTarget tg, double angDeg, double spMm, bool cross) {
    var e = FillPatternElement.GetFillPatternElementByName(d, tg, n); if (e != null) return e;
    FillPattern fp; if (cross) fp = new FillPattern(n, tg, FillPatternHostOrientation.ToView, angDeg * Math.PI / 180, F(spMm), F(spMm)); else fp = new FillPattern(n, tg, FillPatternHostOrientation.ToView, angDeg * Math.PI / 180, F(spMm));
    return FillPatternElement.Create(d, fp); }
  var jiJung = FPE("ZIUM_지중_세로선", FillPatternTarget.Drafting, 90, 2, false);          // SIN36 §6 (LINE 20 / 90°)
  var diag2 = FPE("ZIUM_대각선45_2mm", FillPatternTarget.Drafting, 45, 2, false);         // SIN36 §6 유리난간 (AR-RROOF 근사)
  var solid = FillPatternElement.GetFillPatternElementByName(d, FillPatternTarget.Drafting, "<솔리드 채우기>");
  var sand = FillPatternElement.GetFillPatternElementByName(d, FillPatternTarget.Drafting, "모래");
  var up15 = FillPatternElement.GetFillPatternElementByName(d, FillPatternTarget.Drafting, "대각선으로 위쪽 1.5mm");
  var frBase = new FilteredElementCollector(d).OfClass(typeof(FilledRegionType)).Cast<FilledRegionType>().First(t => t.Name == "솔리드 검은색");
  void FR(string n, FillPatternElement p, Color c, bool transparent = false) { if (p == null) { L.AppendLine("  ! pattern null for " + n); return; }
    var t = ByName<FilledRegionType>(n) ?? (FilledRegionType)frBase.Duplicate(n); t.ForegroundPatternId = p.Id; t.ForegroundPatternColor = c;
    t.BackgroundPatternId = ElementId.InvalidElementId; Try(n + " masking", () => t.IsMasking = !transparent); }
  FR("ZIUM_콘크리트절단_SOLID", solid, RGB(160,160,160));
  FR("ZIUM_지중_세로선", jiJung, RGB(0,0,0), true);
  FR("ZIUM_외벽STO_모래", sand, RGB(200,200,200), true);
  FR("ZIUM_유리난간_대각선", diag2, RGB(200,200,200), true);
  FR("ZIUM_슬래브단부_대각선", up15, RGB(0,0,0), true);
  FR("ZIUM_소방관진입창_SOLID", solid, RGB(255,0,0));
  var kp = ByName<FilledRegionType>("대각선 교차해치 - 투명"); if (kp != null) { var t = ByName<FilledRegionType>("ZIUM_KEYPLAN") ?? (FilledRegionType)kp.Duplicate("ZIUM_KEYPLAN"); }
  // materials (SIN36 §6): concrete cut = solid RGB160; masonry = 대각선 1.5mm; insulation keeps Revit 단열 pattern
  foreach (var m in new FilteredElementCollector(d).OfClass(typeof(Material)).Cast<Material>()) {
    if (m.Name.StartsWith("콘크리트, 현장") || m.Name.StartsWith("콘크리트 - 현장")) { m.CutForegroundPatternId = solid.Id; m.CutForegroundPatternColor = RGB(160,160,160); L.AppendLine("  mat cut solid: " + m.Name); }
    if (m.Name.Contains("조적") && up15 != null) { m.CutForegroundPatternId = up15.Id; m.CutForegroundPatternColor = RGB(128,128,128); L.AppendLine("  mat cut diag: " + m.Name); } }
});
