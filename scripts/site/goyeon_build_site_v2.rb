# v2: quarantines v1 GB_* groups (hidden tags, no deletion), adds canopy-corrected terrain w/ cut pad, lake, real 3DW tree assets.
require 'json'
DIR='C:/Users/USER/grokbot-su/'
d=JSON.parse(File.read(DIR+'site_data_v2.json'))
m=Sketchup.active_model; ents=m.entities
raise 'v2 already built' if ents.grep(Sketchup::Group).any?{|g| g.name.start_with?('GB2_')}
MM=1.m
m.start_operation('Grokbot site context v2',true)
begin
tag=->(n){ m.layers[n] || m.layers.add(n) }
mat=->(n,c,a=1.0){ x=m.materials[n] || m.materials.add(n); x.color=c; x.alpha=a; x }
# 1) quarantine v1 (our own groups only)
{'GB_TREES'=>'Q_TREES_v1_proxy','GB_TERRAIN'=>'Q_TERRAIN_v1_DSM','GB_LAKE'=>'Q_LAKE_v1'}.each{|pre,tn|
  t=tag.(tn); t.visible=false
  ents.grep(Sketchup::Group).select{|g| g.name.start_with?(pre+'_')}.each{|g| g.layer=t } }
# 2) terrain
tg=ents.add_group; tg.name='GB2_TERRAIN_Cop30_canopyCorr_cutPad'; tg.layer=tag.('TERRAIN')
nx,ny,st=d['nx'],d['ny'],d['step']
mesh=Geom::PolygonMesh.new(nx*ny,(nx-1)*(ny-1)*2); idx={}
ny.times{|j| nx.times{|i| idx[[i,j]]=mesh.add_point(Geom::Point3d.new((d['x0']+i*st)*MM,(d['y0']+j*st)*MM,d['grid'][j][i]*MM)) }}
(ny-1).times{|j| (nx-1).times{|i| mesh.add_polygon(idx[[i,j]],idx[[i+1,j]],idx[[i+1,j+1]]); mesh.add_polygon(idx[[i,j]],idx[[i+1,j+1]],idx[[i,j+1]]) }}
tg.entities.fill_from_mesh(mesh,true,Geom::PolygonMesh::AUTO_SOFTEN|Geom::PolygonMesh::SMOOTH_SOFT_EDGES,mat.('GB_Terrain',Sketchup::Color.new(150,140,105)))
tg.set_attribute('GB','note',"Copernicus GLO-30 DSM minus #{d['canopy_m']}m*veg fraction; pad z=0 inside parcel; 1:1.5 cut/fill slopes")
# 3) lake
lg=ents.add_group; lg.name='GB2_LAKE_반계저수지_OSM1242735905'; lg.layer=tag.('LAKE')
pts=d['lake'].map{|x,y| Geom::Point3d.new(x*MM,y*MM,(d['lake_z']+0.3)*MM)}; pts.pop if pts.first==pts.last
f=lg.entities.add_face(pts); f.reverse! if f.normal.z<0
w=mat.('GB_Water',Sketchup::Color.new(40,90,120),0.8); f.material=w; f.back_material=w
# 4) tree definitions from 3D Warehouse assets (glb -> mesh+uv)
defs={}
%w[GB_Tree_PineReal_3DWu1995628d GB_Tree_Pine2D_3DWb17de5 GB_Tree_ZelkovaX_3DW984fbd GB_Tree_Zelkova2D_3DW93501].each{|nm|
  a=JSON.parse(File.read(DIR+"trees/#{nm}.json"))
  cd=m.definitions[nm] || begin
    c=m.definitions.add(nm)
    a['parts'].each_with_index{|p,pi|
      mt=m.materials.add("#{nm}_m#{pi}")
      if p['tex'] then mt.texture=DIR+'trees/'+p['tex'] else mt.color=Sketchup::Color.new(*p['col']) end
      pm=Geom::PolygonMesh.new(p['v'].size,p['f'].size)
      ixs=[]; p['v'].each_with_index{|v,k| ix=pm.add_point(Geom::Point3d.new(v[0]*MM,v[1]*MM,v[2]*MM)); ixs<<ix; pm.set_uv(ix,Geom::Point3d.new(p['uv'][k][0],p['uv'][k][1],1),true) if p['uv'] }
      p['f'].each{|t| pm.add_polygon(ixs[t[0]],ixs[t[1]],ixs[t[2]]) rescue nil }
      c.entities.add_faces_from_mesh(pm,0,mt,mt) }
    c.behavior.always_face_camera=true if nm.include?('2D')
    c.description='3D Warehouse free asset ('+nm.split('_3DW').last+'), converted from public GLB'
    c
  end
  defs[nm]=[cd,a['height']] }
trg=ents.add_group; trg.name='GB2_TREES_3DW_assets_from_imagery'; trg.layer=tag.('TREES')
cx,cy=30.0,20.0; nreal=0; cnt=Hash.new(0); srand(7)
d['trees'].each{|x,y,z,h,sp|
  near=Math.hypot(x-cx,y-cy)<90
  nm = sp=='pine' ? ((near && nreal<200) ? 'GB_Tree_PineReal_3DWu1995628d' : 'GB_Tree_Pine2D_3DWb17de5') : (near ? 'GB_Tree_ZelkovaX_3DW984fbd' : 'GB_Tree_Zelkova2D_3DW93501')
  nreal+=1 if nm.include?('PineReal')
  cd,dh=defs[nm]; hh = sp=='pine' ? h+3 : h; s=hh/dh
  t=Geom::Transformation.translation([x*MM,y*MM,(z-0.2)*MM])*Geom::Transformation.rotation(ORIGIN,Z_AXIS,rand*6.28)*Geom::Transformation.scaling(s,s,s)
  trg.entities.add_instance(cd,t); cnt[nm]+=1 }
m.commit_operation
puts "ok v2 terrain=#{tg.entities.grep(Sketchup::Face).size} lake_z=#{d['lake_z']} trees=#{cnt.to_a.inspect}"
rescue => e
  m.abort_operation; puts "ABORTED: #{e.class}: #{e.message} #{e.backtrace.first(3).inspect}"
end
