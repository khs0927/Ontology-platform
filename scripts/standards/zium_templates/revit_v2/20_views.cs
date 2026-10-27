// ---- viewport type, view templates (SIN36 §5 detail level / §8 names / §9 category hides), levels, sheets ----
Tx("view templates", () => {
  View Mk(View src, string n) { var ex = new FilteredElementCollector(d).OfClass(typeof(View)).Cast<View>().FirstOrDefault(v => v.IsTemplate && v.Name == n); if (ex != null) return ex; var t = src.CreateViewTemplate(); t.Name = n; return t; }
  var plan = new FilteredElementCollector(d).OfClass(typeof(ViewPlan)).Cast<ViewPlan>().First(v => !v.IsTemplate && v.ViewType == ViewType.FloorPlan && v.Name == "레벨 1");
  var elev = new FilteredElementCollector(d).OfClass(typeof(View)).Cast<View>().First(v => !v.IsTemplate && v.ViewType == ViewType.Elevation);
  // a section view is needed as a template source (named Z-tmp per SIN36 §8; kept, not deleted)
  var secT = new FilteredElementCollector(d).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>().First(t => t.ViewFamily == ViewFamily.Section);
  var sec = new FilteredElementCollector(d).OfClass(typeof(ViewSection)).Cast<ViewSection>().FirstOrDefault(v => !v.IsTemplate && v.Name == "Z-tmp-단면 템플릿원본");
  if (sec == null) { var bb = new BoundingBoxXYZ(); bb.Min = new XYZ(-F(10000), -F(1000), -F(3000)); bb.Max = new XYZ(F(10000), F(15000), F(1000));
    bb.Transform = Transform.Identity; var tf = Transform.Identity; tf.BasisX = XYZ.BasisX; tf.BasisY = XYZ.BasisZ; tf.BasisZ = -XYZ.BasisY; bb.Transform = tf;
    sec = ViewSection.CreateSection(d, secT.Id, bb); sec.Name = "Z-tmp-단면 템플릿원본"; }
  var draft = new FilteredElementCollector(d).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>().First(t => t.ViewFamily == ViewFamily.Drafting);
  var hideCats = new[] { BuiltInCategory.OST_Entourage, BuiltInCategory.OST_Mass, BuiltInCategory.OST_Cameras, BuiltInCategory.OST_PointClouds, BuiltInCategory.OST_RasterImages };
  void Cfg(View t, int scale, ViewDetailLevel dl, bool hideLights) { t.Scale = scale; t.DetailLevel = dl; Try("style", () => t.DisplayStyle = DisplayStyle.HLR);
    foreach (var b in hideCats) Try("hide " + b, () => t.SetCategoryHidden(new ElementId(b), true));
    if (hideLights) Try("hide lights", () => t.SetCategoryHidden(new ElementId(BuiltInCategory.OST_LightingFixtures), true));
    Try("topo contours", () => { var tc = d.Settings.Categories.get_Item(BuiltInCategory.OST_Toposolid); foreach (Category s in tc.SubCategories) if (s.Name.Contains("등고선") || s.Name.ToLower().Contains("contour")) t.SetCategoryHidden(s.Id, true); }); }
  // scales: SIN36 §1 A1 denominators (plan 1/60, elev/sec 1/100, site 1/300, detail 1/30, key 1/800)
  Cfg(Mk(plan, "Z-평면"), 60, ViewDetailLevel.Medium, true);
  Cfg(Mk(plan, "Z-배치"), 300, ViewDetailLevel.Medium, true);
  Cfg(Mk(plan, "Z-KEY PLAN"), 800, ViewDetailLevel.Coarse, true);
  Cfg(Mk(plan, "Z-상세"), 30, ViewDetailLevel.Fine, false);
  Cfg(Mk(elev, "Z-입면"), 100, ViewDetailLevel.Medium, true);
  Cfg(Mk(sec, "Z-단면"), 100, ViewDetailLevel.Medium, true);
  // viewport: titles drawn on sheet -> make 제목 없음 the default viewport style used by ZIUM (SIN36 §1)
  var vp = ET("뷰포트", "제목 없음"); if (vp != null) { var z = ET("뷰포트", "ZIUM 제목 없음") ?? vp.Duplicate("ZIUM 제목 없음"); L.AppendLine("  viewport type ZIUM 제목 없음 " + z.Id); }
});
Tx("levels+views names", () => {
  // YUJIN guide / SIN36 §4 level naming; template has 레벨 1/레벨 2 only
  foreach (var lv in new FilteredElementCollector(d).OfClass(typeof(Level)).Cast<Level>().ToList()) { if (lv.Name == "레벨 1") lv.Name = "1ST S.L"; else if (lv.Name == "레벨 2") lv.Name = "2ND S.L"; }
  foreach (var v in new FilteredElementCollector(d).OfClass(typeof(View)).Cast<View>().Where(v => !v.IsTemplate).ToList()) {
    string n = null;
    if (v.ViewType == ViewType.Elevation) n = v.Name == "남쪽" ? "Z-정면도" : v.Name == "북쪽" ? "Z-배면도" : v.Name == "동쪽" ? "Z-우측면도" : v.Name == "서쪽" ? "Z-좌측면도" : null;
    if (v.ViewType == ViewType.FloorPlan && v.Name == "1ST S.L") n = "Z-1층 평면도"; if (v.ViewType == ViewType.FloorPlan && v.Name == "2ND S.L") n = "Z-2층 평면도"; if (v.ViewType == ViewType.FloorPlan && v.Name == "대지") n = "Z-배치도";
    if (n != null) Try("rename " + v.Name, () => v.Name = n); }
  var tplFor = new Dictionary<string, string> { { "Z-1층 평면도", "Z-평면" }, { "Z-2층 평면도", "Z-평면" }, { "Z-배치도", "Z-배치" }, { "Z-정면도", "Z-입면" }, { "Z-배면도", "Z-입면" }, { "Z-우측면도", "Z-입면" }, { "Z-좌측면도", "Z-입면" } };
  foreach (var kv in tplFor) { var v = new FilteredElementCollector(d).OfClass(typeof(View)).Cast<View>().FirstOrDefault(x => !x.IsTemplate && x.Name == kv.Key); var t = new FilteredElementCollector(d).OfClass(typeof(View)).Cast<View>().FirstOrDefault(x => x.IsTemplate && x.Name == kv.Value); if (v != null && t != null) Try("vt " + kv.Key, () => v.ViewTemplateId = t.Id); }
});
