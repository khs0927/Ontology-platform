# Read-only SketchUp model dump. Never modifies the model.
require 'json'
module GrokDump
  MAX_NODES = 8000
  MAX_DEPTH = 8
  def self.mm(v); (v.to_f * 25.4).round(1); end
  def self.pt(p); [mm(p.x), mm(p.y), mm(p.z)]; end
  def self.s(v, n = 400)
    str = v.to_s
    str = str.dup.force_encoding('UTF-8')
    str = str.encode('UTF-8', invalid: :replace, undef: :replace, replace: '?') unless str.valid_encoding?
    str.length > n ? str[0, n] + '...' : str
  end
  def self.val(v)
    case v
    when Integer, Float, TrueClass, FalseClass, NilClass then v
    when String then s(v)
    when Array then v.first(30).map { |x| val(x) }
    when Length then v.to_f
    else s(v)
    end
  end
  def self.attrs(e)
    out = {}
    ds = e.attribute_dictionaries
    return out unless ds
    ds.each do |d|
      h = {}
      d.each_pair { |k, v| h[s(k, 80)] = val(v) if h.size < 120 }
      out[s(d.name, 80)] = h
    end
    out
  rescue => ex
    { '_error' => ex.message }
  end
  def self.bb(b)
    return nil if b.nil? || b.empty?
    { 'min' => pt(b.min), 'max' => pt(b.max), 'size' => [mm(b.width), mm(b.height), mm(b.depth)] }
  end
  def self.world_bb(defn, tr)
    b = defn.bounds
    return nil if b.empty?
    nb = Geom::BoundingBox.new
    (0..7).each { |i| nb.add(b.corner(i).transform(tr)) }
    bb(nb)
  end
  def self.layer_path(l)
    return nil unless l
    parts = [l.name]
    f = l.respond_to?(:folder) ? l.folder : nil
    while f
      parts.unshift(f.name)
      f = f.respond_to?(:folder) ? f.folder : nil
    end
    parts.join('/')
  end
  def self.tr_info(t)
    a = t.to_a
    sx = Math.sqrt(a[0]**2 + a[1]**2 + a[2]**2)
    sy = Math.sqrt(a[4]**2 + a[5]**2 + a[6]**2)
    sz = Math.sqrt(a[8]**2 + a[9]**2 + a[10]**2)
    rotz = (Math.atan2(a[1], a[0]) * 180.0 / Math::PI).round(2)
    { 'origin' => pt(t.origin), 'scale' => [sx.round(4), sy.round(4), sz.round(4)], 'rot_z_deg' => rotz,
      'xaxis' => t.xaxis.to_a.map { |x| x.round(4) }, 'zaxis' => t.zaxis.to_a.map { |x| x.round(4) } }
  end
  def self.count_ents(ents)
    c = Hash.new(0)
    ents.each { |e| c[e.typename] += 1 }
    c
  end

  def self.run(outpath)
    m = Sketchup.active_model
    t0 = Time.now
    d = {}
    d['_meta'] = { 'tool' => 'grokbot read-only dump v1', 'sketchup_version' => Sketchup.version,
                   'dumped_at' => Time.now.to_s, 'length_unit' => 'mm', 'area_unit' => 'm2' }
    uo = {}
    m.options['UnitsOptions'].each { |k, v| uo[k] = val(v) } rescue nil
    si = {}
    begin
      %w[City Country Latitude Longitude NorthAngle TZOffset DisplayShadows ShadowTime].each { |k| si[k] = val(m.shadow_info[k]) }
    rescue; end
    d['model'] = { 'title' => s(m.title), 'path' => s(m.path), 'description' => s(m.description, 2000),
                   'modified' => m.modified?, 'georeferenced' => (m.georeferenced? rescue nil),
                   'units_options' => uo, 'shadow_info' => si, 'bounds' => bb(m.bounds),
                   'top_level_count' => m.entities.size, 'top_level_types' => count_ents(m.entities),
                   'definitions_count' => m.definitions.size, 'layers_count' => m.layers.size,
                   'materials_count' => m.materials.size, 'pages_count' => m.pages.size,
                   'styles_count' => m.styles.size, 'attributes' => attrs(m),
                   'active_layer' => (m.active_layer.name rescue nil),
                   'axes' => (m.axes ? { 'origin' => pt(m.axes.origin), 'xaxis' => m.axes.xaxis.to_a.map { |x| x.round(4) } } : nil) }
    # styles
    d['styles'] = m.styles.map { |st| { 'name' => s(st.name), 'description' => s(st.description), 'active' => (m.styles.active_style == st), 'selected' => (m.styles.selected_style == st) } }
    # pages
    d['pages'] = m.pages.map do |pg|
      cam = pg.camera
      h = { 'name' => s(pg.name), 'label' => (s(pg.label) rescue nil), 'description' => s(pg.description),
            'use_camera' => pg.use_camera?, 'use_hidden_layers' => pg.use_hidden_layers?,
            'use_style' => pg.use_style?, 'use_section_planes' => pg.use_section_planes?,
            'use_axes' => pg.use_axes?, 'use_shadow_info' => pg.use_shadow_info?,
            'style' => (pg.style ? s(pg.style.name) : nil),
            'hidden_layers' => (pg.layers || []).map { |l| s(l.name) },
            'hidden_entities_count' => (pg.hidden_entities.size rescue nil),
            'camera' => cam ? { 'eye' => pt(cam.eye), 'target' => pt(cam.target), 'up' => cam.up.to_a.map { |x| x.round(3) }, 'perspective' => cam.perspective?, 'fov' => (cam.perspective? ? cam.fov.round(2) : nil), 'height_mm' => (cam.perspective? ? nil : mm(cam.height)) } : nil }
      h['layer_folders_hidden'] = (pg.layer_folders.map { |f| s(f.name) } rescue nil)
      h
    end
    d['selected_page'] = (m.pages.selected_page ? s(m.pages.selected_page.name) : nil)
    # layer folders
    folders = []
    walk_f = lambda do |f, prefix|
      p = prefix ? "#{prefix}/#{f.name}" : f.name
      folders << { 'path' => s(p), 'visible' => f.visible?, 'layers' => f.layers.map { |l| s(l.name) } }
      f.folders.each { |sf| walk_f.call(sf, p) } if f.respond_to?(:folders)
    end
    (m.layers.folders.each { |f| walk_f.call(f, nil) } rescue nil)
    d['layer_folders'] = folders
    # usage counters
    layer_use = Hash.new { |h, k| h[k] = Hash.new(0) }
    mat_use = Hash.new { |h, k| h[k] = Hash.new(0) }
    defs_out = []
    texts = []
    dims = []
    totals = Hash.new(0)
    m.definitions.each do |df|
      ents = df.entities
      tc = Hash.new(0)
      dl = Hash.new(0)
      dm = Hash.new(0)
      area = 0.0
      child = Hash.new(0)
      ents.each do |e|
        tn = e.typename
        tc[tn] += 1
        ln = e.respond_to?(:layer) && e.layer ? e.layer.name : nil
        if ln
          dl[ln] += 1
          layer_use[ln][tn] += 1
        end
        if e.respond_to?(:material) && e.material
          dm[e.material.name] += 1
          mat_use[e.material.name][tn] += 1
        end
        if e.is_a?(Sketchup::Face)
          area += e.area
          if e.back_material
            mat_use[e.back_material.name]['Face(back)'] += 1
            dm[e.back_material.name] += 1
          end
        end
        child[e.definition.name] += 1 if e.is_a?(Sketchup::ComponentInstance)
        child[e.definition.name] += 1 if e.is_a?(Sketchup::Group)
        if e.is_a?(Sketchup::Text) && texts.size < 400
          texts << { 'in_def' => s(df.name), 'text' => s(e.text, 200), 'layer' => ln, 'point' => (e.point ? pt(e.point) : nil) }
        end
        if e.is_a?(Sketchup::Dimension) && dims.size < 400
          dims << { 'in_def' => s(df.name), 'text' => (s(e.text, 80) rescue nil), 'type' => e.typename, 'layer' => ln }
        end
        totals[tn] += 1 unless df.image?
      end
      beh = df.behavior
      defs_out << { 'name' => s(df.name), 'guid' => df.guid, 'description' => s(df.description, 600),
                    'kind' => (df.group? ? 'group' : (df.image? ? 'image' : 'component')),
                    'internal' => (df.internal? rescue nil), 'path' => (s(df.path) rescue nil),
                    'instances' => df.instances.size, 'used_instances' => (df.count_used_instances rescue nil),
                    'bounds_size' => (df.bounds.empty? ? nil : [mm(df.bounds.width), mm(df.bounds.height), mm(df.bounds.depth)]),
                    'bounds' => bb(df.bounds), 'insertion_point' => pt(df.insertion_point),
                    'entity_counts' => tc, 'face_area_m2' => (area * 0.00064516).round(3),
                    'child_definitions' => child, 'layers_used' => dl, 'materials_used' => dm,
                    'behavior' => { 'is2d' => beh.is2d?, 'cuts_opening' => beh.cuts_opening?, 'always_face_camera' => beh.always_face_camera?, 'snapto' => beh.snapto, 'no_scale_mask' => (beh.no_scale_mask? rescue nil) },
                    'instance_layers' => df.instances.map { |i| i.layer ? i.layer.name : nil }.tally,
                    'attributes' => attrs(df) }
    end
    d['totals_definition_level'] = totals
    d['texts'] = texts
    d['dimensions'] = dims
    # layers
    d['layers'] = m.layers.map do |l|
      c = l.color
      { 'name' => s(l.name), 'display_name' => (s(l.display_name) rescue nil), 'path' => s(layer_path(l)),
        'visible' => l.visible?, 'color' => [c.red, c.green, c.blue, c.alpha],
        'line_style' => (l.line_style ? s(l.line_style.name) : nil), 'page_behavior' => l.page_behavior,
        'persistent_id' => (l.persistent_id rescue nil),
        'usage_by_type' => layer_use[l.name], 'usage_total' => layer_use[l.name].values.sum, 'attributes' => attrs(l) }
    end
    # materials
    d['materials'] = m.materials.map do |mt|
      c = mt.color
      tx = mt.texture
      { 'name' => s(mt.name), 'display_name' => s(mt.display_name), 'color' => [c.red, c.green, c.blue],
        'alpha' => mt.alpha.round(3), 'use_alpha' => mt.use_alpha?, 'type' => mt.materialType,
        'texture' => tx ? { 'filename' => s(File.basename(tx.filename.to_s)), 'width_mm' => mm(tx.width), 'height_mm' => mm(tx.height), 'image_px' => [tx.image_width, tx.image_height] } : nil,
        'colorize_type' => (mt.colorize_type rescue nil),
        'workflow' => (mt.respond_to?(:workflow) ? s(mt.workflow) : nil),
        'usage_by_type' => mat_use[mt.name], 'usage_total' => mat_use[mt.name].values.sum,
        'attributes' => attrs(mt) }
    end
    d['definitions'] = defs_out
    # hierarchy
    nodes = []
    truncated = 0
    walk = nil
    walk = lambda do |ents, tr, depth, parent_id, path|
      ents.each do |e|
        next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
        if nodes.size >= MAX_NODES || depth > MAX_DEPTH
          truncated += 1
          next
        end
        df = e.definition
        wt = tr * e.transformation
        nm = e.name.to_s
        label = nm.empty? ? df.name : nm
        npath = path + [label]
        cc = Hash.new(0)
        df.entities.each { |x| cc[x.typename] += 1 }
        nodes << { 'pid' => e.persistent_id, 'parent_pid' => parent_id, 'depth' => depth,
                   'type' => e.typename, 'name' => s(nm), 'definition' => s(df.name),
                   'path' => npath.map { |x| s(x, 120) }.join(' > '),
                   'layer' => (e.layer ? s(e.layer.name) : nil), 'material' => (e.material ? s(e.material.name) : nil),
                   'visible' => e.visible?, 'locked' => (e.respond_to?(:locked?) ? e.locked? : nil),
                   'transform' => tr_info(e.transformation), 'world_bounds' => world_bb(df, wt),
                   'child_counts' => cc, 'attributes' => attrs(e) }
        walk.call(df.entities, wt, depth + 1, e.persistent_id, npath)
      end
    end
    walk.call(m.entities, Geom::Transformation.new, 0, nil, [])
    d['hierarchy'] = nodes
    d['hierarchy_truncated'] = truncated
    # top-level loose
    top = []
    m.entities.each do |e|
      next if e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
      top << { 'type' => e.typename, 'layer' => (e.respond_to?(:layer) && e.layer ? e.layer.name : nil), 'pid' => e.persistent_id }
    end
    d['top_level_loose'] = top
    d['top_level_loose_summary'] = top.group_by { |x| [x['type'], x['layer']] }.map { |k, v| { 'type' => k[0], 'layer' => k[1], 'count' => v.size } }
    # section planes
    sp = []
    m.definitions.each { |df| df.entities.grep(Sketchup::SectionPlane).each { |e| sp << { 'in_def' => s(df.name), 'name' => (s(e.name) rescue nil), 'active' => e.active?, 'plane' => e.get_plane.map { |x| x.round(4) } } } }
    m.entities.grep(Sketchup::SectionPlane).each { |e| sp << { 'in_def' => '(model)', 'name' => (s(e.name) rescue nil), 'active' => e.active?, 'plane' => e.get_plane.map { |x| x.round(4) } } }
    d['section_planes'] = sp
    d['_meta']['elapsed_s'] = (Time.now - t0).round(2)
    File.open(outpath, 'w:UTF-8') { |f| f.write(JSON.pretty_generate(d)) }
    "ok nodes=#{nodes.size} truncated=#{truncated} defs=#{defs_out.size} bytes=#{File.size(outpath)} t=#{d['_meta']['elapsed_s']}"
  end
end
# Output dir: $SION_SU_EXPORT_DIR, else %USERPROFILE%/grokbot-mcp-bridge/export (must exist).
GrokDump.run(File.join(ENV['SION_SU_EXPORT_DIR'] || File.join(ENV['USERPROFILE'] || Dir.home, 'grokbot-mcp-bridge', 'export'), 'model_dump.json'))
