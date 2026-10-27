# Build ZIUM SketchUp template + GOYEON1525 smoke mass without changing the open model (operation is aborted).
require 'fileutils'
out = 'C:/CODE/zium-templates/sketchup'
FileUtils.mkdir_p(out)
m = Sketchup.active_model
# Source: Ontology-platform docs/sketchup/MODELING-GUIDELINES.ko.md "tags" [권장] list
tags = ['@3D-대지','옹벽','@주차','@wall','@door','@win','@stair','@FUR','Trees 3D','@사람','@DIM','CAD-참조']
res = {}
m.start_operation('zium_tpl_tmp', true)
begin
  root = m.entities.add_group
  root.name = 'ZIUM_TEMPLATE'
  tags.each do |t|
    l = m.layers[t] || m.layers.add(t)
    g = root.entities.add_group
    g.name = t
    g.entities.add_cpoint(ORIGIN)   # keeps the empty group alive; geometry stays on Layer0
    g.layer = l
  end
  res[:skp] = root.definition.save_as("#{out}/ZIUM_template_tags.skp")
  # smoke mass (placeholder 10x10x7 m, not a design value)
  mass = m.entities.add_group
  mass.name = 'GOYEON1525_MASS_SMOKE'
  f = mass.entities.add_face([0,0,0],[10.m,0,0],[10.m,10.m,0],[0,10.m,0])
  f.reverse! if f.normal.z < 0
  f.pushpull(7.m)
  mass.layer = m.layers['@wall']
  smoke = 'C:/CODE/zium-templates/smoke'
  FileUtils.mkdir_p(smoke)
  res[:mass_skp] = mass.definition.save_as("#{smoke}/GOYEON1525_mass.skp")
  m.selection.clear; m.selection.add(mass)
  res[:ifc] = m.export("#{smoke}/GOYEON1525_mass.ifc", {:selectionset_only => true, :show_summary => false}) rescue res[:ifc_err] = $!.message
ensure
  m.abort_operation
  m.selection.clear
end
res[:after_entities] = m.entities.size
res[:after_layers] = m.layers.size
res.inspect
