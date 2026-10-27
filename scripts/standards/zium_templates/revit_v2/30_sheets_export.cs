// ---- titleblock (ZIUM_도곽_A1.rfa from the v1/hillside port) + generic sheet set (SIN36 §10 numbering scheme A0xx/A1xx/A2xx/A3xx/A4xx/A5xx) ----
const string TBRFA = @"C:\Users\khs09\Documents\revit_mcp\families\ZIUM_도곽_A1.rfa";
Family tbF = new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().FirstOrDefault(f => f.Name == "ZIUM_도곽_A1");
if (tbF == null) Tx("load titleblock", () => { d.LoadFamily(TBRFA, out tbF); });
Tx("sheets", () => {
  var sym = new FilteredElementCollector(d).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_TitleBlocks).Cast<FamilySymbol>().First(s => s.FamilyName == "ZIUM_도곽_A1"); if (!sym.IsActive) sym.Activate();
  var have = new HashSet<string>(new FilteredElementCollector(d).OfClass(typeof(ViewSheet)).Cast<ViewSheet>().Select(s => s.SheetNumber));
  var list = new (string no, string nm)[] { ("A000","표지 및 도면목록"),("A001","건축개요 및 법규검토표"),("A002","배치도"),("A003","면적표"),("A101","정면도, 배면도"),("A102","우측면도, 좌측면도"),
    ("A201","1층 평면도"),("A202","2층 평면도"),("A301","단면도-1"),("A302","단면도-2"),("A401","상세도"),("A501","주차장 평면도") };
  foreach (var s in list) if (!have.Contains(s.no)) { var sh = ViewSheet.Create(d, sym.Id); sh.SheetNumber = s.no; sh.Name = s.nm; }
});
// ---- DWG export settings: ZIUM_DWG (category/line-style layer table, SIN36 §11) + ZIUM_YUJIN (layer mapping file) ----
Tx("dwg export", () => {
  var map = new Dictionary<BuiltInCategory, (string l, int c)> {
    { BuiltInCategory.OST_Walls, ("COL", 2) }, { BuiltInCategory.OST_Columns, ("COL", 2) }, { BuiltInCategory.OST_StructuralColumns, ("COL", 2) }, { BuiltInCategory.OST_Floors, ("COL", 2) }, { BuiltInCategory.OST_Roofs, ("COL", 2) }, { BuiltInCategory.OST_StructuralFraming, ("COL", 2) },
    { BuiltInCategory.OST_Ceilings, ("CEIL", 5) }, { BuiltInCategory.OST_Doors, ("DOOR", 4) }, { BuiltInCategory.OST_Windows, ("WIN", 4) }, { BuiltInCategory.OST_CurtainWallPanels, ("WIN", 4) }, { BuiltInCategory.OST_CurtainWallMullions, ("WINBAR", 4) },
    { BuiltInCategory.OST_Stairs, ("STAIR", 7) }, { BuiltInCategory.OST_StairsRailing, ("STAIR", 7) }, { BuiltInCategory.OST_Furniture, ("FUR", 7) }, { BuiltInCategory.OST_LightingFixtures, ("FIX", 154) }, { BuiltInCategory.OST_PlumbingFixtures, ("FIX", 154) },
    { BuiltInCategory.OST_Parking, ("PARKING", 7) }, { BuiltInCategory.OST_Planting, ("ETC", 8) }, { BuiltInCategory.OST_Entourage, ("ETC", 8) }, { BuiltInCategory.OST_Toposolid, ("ETC", 8) }, { BuiltInCategory.OST_Site, ("ETC", 8) }, { BuiltInCategory.OST_DetailComponents, ("ETC", 8) }, { BuiltInCategory.OST_RasterImages, ("ETC", 8) },
    { BuiltInCategory.OST_GenericModel, ("ETC1", 251) }, { BuiltInCategory.OST_FilledRegion, ("HAT", 5) }, { BuiltInCategory.OST_Dimensions, ("DIM", 7) }, { BuiltInCategory.OST_Grids, ("CEN", 1) }, { BuiltInCategory.OST_GridHeads, ("SYM", 7) }, { BuiltInCategory.OST_Levels, ("CEN1", 1) }, { BuiltInCategory.OST_LevelHeads, ("SYM", 7) },
    { BuiltInCategory.OST_TextNotes, ("TXT", 3) }, { BuiltInCategory.OST_ScheduleGraphics, ("TXT", 3) }, { BuiltInCategory.OST_RoomTags, ("실명", 7) }, { BuiltInCategory.OST_Rooms, ("실명", 7) }, { BuiltInCategory.OST_Sections, ("SYM", 7) }, { BuiltInCategory.OST_SectionHeads, ("SYM", 7) },
    { BuiltInCategory.OST_Elev, ("SYM", 7) }, { BuiltInCategory.OST_ElevationMarks, ("SYM", 7) }, { BuiltInCategory.OST_Viewers, ("SYM", 7) }, { BuiltInCategory.OST_GenericAnnotation, ("SYM", 7) }, { BuiltInCategory.OST_TitleBlocks, ("A-FORM", 7) }, { BuiltInCategory.OST_Viewports, ("TIT", 7) } };
  var lineMap = new Dictionary<string, (string l, int c)> { { "ZIUM_TIT", ("TIT", 7) }, { "ZIUM_TIT_가는선", ("TIT", 7) }, { "ZIUM_표", ("TXT", 3) }, { "ZIUM_표_굵은선", ("TXT", 3) }, { "ZIUM_대지경계선", ("AREA", 6) }, { "ZIUM_도로선", ("ETC", 8) }, { "ZIUM_주출입구", ("SYM", 1) },
    { "ZIUM_지반선", ("ETC", 8) }, { "ZIUM_KEY", ("SYM", 6) }, { "ZIUM_건축선", ("AREA", 1) }, { "ZIUM_숨은선", ("ETC", 8) }, { "ZIUM_레벨선", ("CEN1", 1) }, { "ZIUM_중심선", ("CEN", 1) }, { "ZIUM_입면외곽", ("ELE", 8) }, { "ZIUM_가는선", ("ETC", 8) } };
  var st = new FilteredElementCollector(d).OfClass(typeof(ExportDWGSettings)).Cast<ExportDWGSettings>().FirstOrDefault(q => q.Name == "ZIUM_DWG") ?? ExportDWGSettings.Create(d, "ZIUM_DWG");
  var o = st.GetDWGExportOptions(); var tbl = o.GetExportLayerTable(); var ln = LinesCat().Name; int mapped = 0;
  foreach (var k in tbl.GetKeys()) { (string l, int c) t = (null, 0);
    if (k.CategoryName == ln && lineMap.ContainsKey(k.SubCategoryName ?? "")) t = lineMap[k.SubCategoryName];
    else if (string.IsNullOrEmpty(k.SubCategoryName) || k.CategoryName != ln) { Category cat = null; try { cat = d.Settings.Categories.get_Item(k.CategoryName); } catch { } if (cat != null && map.ContainsKey((BuiltInCategory)cat.Id.Value)) t = map[(BuiltInCategory)cat.Id.Value]; }
    if (t.l == null) continue; var info = tbl[k]; info.LayerName = t.l; info.ColorNumber = t.c; info.CutLayerName = t.l; info.CutColorNumber = t.c; tbl[k] = info; mapped++; }
  o.SetExportLayerTable(tbl); o.FileVersion = ACADVersion.R2018; o.TargetUnit = ExportUnit.Millimeter; o.SharedCoords = false; o.MergedViews = true; o.ExportOfSolids = SolidGeometry.Polymesh; o.HideScopeBox = true; o.HideReferencePlane = true; o.HideUnreferenceViewTags = true;
  st.SetDWGExportOptions(o); L.AppendLine($"  ZIUM_DWG mapped={mapped}/{tbl.GetKeys().Count}");
  var st2 = new FilteredElementCollector(d).OfClass(typeof(ExportDWGSettings)).Cast<ExportDWGSettings>().FirstOrDefault(q => q.Name == "ZIUM_YUJIN") ?? ExportDWGSettings.Create(d, "ZIUM_YUJIN");
  var o2 = st.GetDWGExportOptions(); Try("yujin map file", () => o2.LayerMapping = @"C:\CODE\zium-templates\revit\ZIUM_YUJIN_layers.txt"); st2.SetDWGExportOptions(o2);
});
