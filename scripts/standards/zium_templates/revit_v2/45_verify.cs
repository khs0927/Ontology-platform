
foreach(var f in new FilteredElementCollector(d).OfClass(typeof(Family)).Cast<Family>().Where(x=>x.Name.StartsWith("ZIUM"))) L.AppendLine("fam "+f.Name);
foreach(var g in new FilteredElementCollector(d).OfClass(typeof(GridType)).Cast<GridType>().Where(x=>x.Name.StartsWith("ZIUM"))){var p=g.get_Parameter(BuiltInParameter.GRID_HEAD_TAG);L.AppendLine("grid "+g.Name+" head="+(p==null?"-":d.GetElement(p.AsElementId())?.Name));}
foreach(var l in new FilteredElementCollector(d).OfClass(typeof(Level)).Cast<Level>()) L.AppendLine("level "+l.Name+" type="+d.GetElement(l.GetTypeId()).Name);
foreach(var v in new FilteredElementCollector(d).OfClass(typeof(ElementType)).Cast<ElementType>().Where(x=>x.Name=="ZIUM 뷰제목")){var p=v.get_Parameter(BuiltInParameter.VIEWPORT_ATTR_LABEL_TAG);L.AppendLine("vp "+v.Name+" tag="+(p==null?"-":d.GetElement(p.AsElementId())?.Name));}

