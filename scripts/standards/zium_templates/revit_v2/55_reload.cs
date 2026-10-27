// reload ZIUM families (font already set in rfa by 50_font) with an emitted IFamilyLoadOptions that overwrites
var ab = System.Reflection.Emit.AssemblyBuilder.DefineDynamicAssembly(new System.Reflection.AssemblyName("ZOptAsm"), System.Reflection.Emit.AssemblyBuilderAccess.Run);
var tb = ab.DefineDynamicModule("m").DefineType("ZOpt", System.Reflection.TypeAttributes.Public | System.Reflection.TypeAttributes.Class);
tb.AddInterfaceImplementation(typeof(IFamilyLoadOptions));
var VA = System.Reflection.MethodAttributes.Public | System.Reflection.MethodAttributes.Virtual | System.Reflection.MethodAttributes.Final | System.Reflection.MethodAttributes.HideBySig | System.Reflection.MethodAttributes.NewSlot;
foreach (var im in typeof(IFamilyLoadOptions).GetMethods()) {
  var ps = im.GetParameters();
  var mb = tb.DefineMethod(im.Name, VA, typeof(bool), ps.Select(p => p.ParameterType).ToArray());
  var il = mb.GetILGenerator();
  for (int i = 0; i < ps.Length; i++) { var pt = ps[i].ParameterType; if (!pt.IsByRef) continue; var et = pt.GetElementType();
    il.Emit(System.Reflection.Emit.OpCodes.Ldarg, (short)(i + 1));
    if (et == typeof(bool)) { il.Emit(System.Reflection.Emit.OpCodes.Ldc_I4_1); il.Emit(System.Reflection.Emit.OpCodes.Stind_I1); }
    else { il.Emit(System.Reflection.Emit.OpCodes.Ldc_I4, (int)FamilySource.Family); il.Emit(System.Reflection.Emit.OpCodes.Stind_I4); } }
  il.Emit(System.Reflection.Emit.OpCodes.Ldc_I4_1); il.Emit(System.Reflection.Emit.OpCodes.Ret);
  tb.DefineMethodOverride(mb, im); }
var opt = (IFamilyLoadOptions)Activator.CreateInstance(tb.CreateType());
foreach (Document x in A.Documents.Cast<Document>().ToList()) if (x.IsFamilyDocument && x.Title.StartsWith("ZIUM")) Try("close " + x.Title, () => { x.Close(false); });
var dir = @"C:\CODE\zium-templates\revit\families\";
foreach (var n in new[] { "ZIUM_도곽_A1", "ZIUM_방위표", "ZIUM_그리드헤드", "ZIUM_레벨헤드", "ZIUM_뷰제목", "ZIUM_실명박스_22", "ZIUM_실명박스_30", "ZIUM_실명박스_40" }) Try(n, () => {
  Family f; bool ok; using (var t = new Transaction(d, "reload " + n)) { t.Start(); ok = d.LoadFamily(dir + n + ".rfa", opt, out f); t.Commit(); }
  L.AppendLine("  reload " + n + " " + ok); });
// verify fonts incl. family label types
foreach (var fam in new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().Where(f => f.Name.StartsWith("ZIUM")).ToList()) Try("chk " + fam.Name, () => {
  var fd = d.EditFamily(fam);
  var fs = new FilteredElementCollector(fd).OfClass(typeof(ElementType)).Cast<ElementType>().Select(t => t.get_Parameter(BuiltInParameter.TEXT_FONT)?.AsString()).Where(s => s != null).Distinct();
  L.AppendLine("  font " + fam.Name + ": " + string.Join(",", fs)); fd.Close(false); });
L.AppendLine("project fonts: " + string.Join(", ", new FilteredElementCollector(d).OfClass(typeof(ElementType)).Cast<ElementType>().Select(t => t.get_Parameter(BuiltInParameter.TEXT_FONT)?.AsString()).Where(s => s != null).GroupBy(s => s).Select(g => g.Key + "=" + g.Count())));
