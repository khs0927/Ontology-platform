# Read-only grouping/organisation probe. Walks the full instance tree (all depths) and every
# definition; writes JSON. Never modifies the model (no create/move/delete/save/undo/purge).
require 'json'
module GrokGroupingProbe
  MAX_DEPTH = 12
  def self.mm(v); (v.to_f * 25.4).round(1); end
  def self.pt(p); [mm(p.x), mm(p.y), mm(p.z)]; end
  def self.vec(v); [v.x.round(4), v.y.round(4), v.z.round(4)]; end
  def self.lname(e); e.respond_to?(:layer) && e.layer ? e.layer.name : nil; end
  def self.inst?(e); e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance); end

  def self.run(out)
    m = Sketchup.active_model
    t0 = Time.now
    nodes = []
    walk = lambda do |ents, parent_path, depth|
      ents.each do |e|
        next unless inst?(e)
        d = e.definition
        t = e.transformation
        path = parent_path + [e.persistent_id]
        sc = [t.xaxis.length, t.yaxis.length, t.zaxis.length].map { |x| x.to_f.round(4) }
        glued = (e.glued_to rescue nil)
        nodes << {
          'pid_path' => path, 'depth' => depth, 'type' => e.typename, 'name' => e.name.to_s,
          'definition' => d.name, 'layer' => lname(e), 'material' => (e.material ? e.material.name : nil),
          'locked' => (e.locked? rescue nil), 'hidden' => e.hidden?,
          'glued_to' => glued ? { 'type' => glued.typename, 'pid' => (glued.persistent_id rescue nil) } : nil,
          'local_identity' => t.identity?, 'local_origin' => pt(t.origin),
          'local_xaxis' => vec(t.xaxis.normalize), 'local_zaxis' => vec(t.zaxis.normalize), 'local_scale' => sc,
          'mirrored' => (t.xaxis * t.yaxis) % t.zaxis < 0
        }
        walk.call(d.entities, path, depth + 1) if depth < MAX_DEPTH
      end
    end
    walk.call(m.entities, [], 0)

    defs = []
    m.definitions.each do |d|
      next if d.image?
      raw = Hash.new { |h, k| h[k] = Hash.new(0) }
      kids = Hash.new { |h, k| h[k] = Hash.new(0) }
      other = Hash.new(0)
      d.entities.each do |x|
        if inst?(x)
          kids[x.typename][lname(x).to_s] += 1
        elsif x.is_a?(Sketchup::Face) || x.is_a?(Sketchup::Edge)
          raw[x.typename][lname(x).to_s] += 1
        else
          other[x.typename] += 1
        end
      end
      b = d.bounds
      defs << {
        'name' => d.name, 'kind' => d.group? ? 'group' : 'component', 'count_instances' => d.count_instances,
        'raw_geometry_by_layer' => raw, 'child_instances_by_layer' => kids, 'other_entities' => other,
        'bounds_min' => pt(b.min), 'bounds_max' => pt(b.max), 'insertion_point' => pt(d.insertion_point),
        'description' => d.description.to_s[0, 200],
        'behavior' => { 'cuts_opening' => d.behavior.cuts_opening?, 'is2d' => d.behavior.is2d?,
                        'snapto' => d.behavior.snapto, 'always_face_camera' => d.behavior.always_face_camera?,
                        'shadows_face_sun' => d.behavior.shadows_face_sun?, 'no_scale_mask' => d.behavior.no_scale_mask? }
      }
    end
    res = {
      '_meta' => { 'tool' => 'grokbot read-only grouping probe v1', 'dumped_at' => Time.now.strftime('%Y-%m-%d %H:%M:%S %z'),
                   'model' => m.title, 'length_unit' => 'mm', 'elapsed_s' => (Time.now - t0).round(2) },
      'model_modified' => m.modified?, 'active_path' => (m.active_path || []).map { |e| e.persistent_id },
      'nodes' => nodes, 'definitions' => defs
    }
    File.open(out, 'w:UTF-8') { |f| f.write(JSON.pretty_generate(res)) }
    "ok nodes=#{nodes.size} defs=#{defs.size}"
  end
end
# Output dir: $SION_SU_EXPORT_DIR, else %USERPROFILE%/grokbot-mcp-bridge/export (must exist).
GrokGroupingProbe.run(File.join(ENV['SION_SU_EXPORT_DIR'] || File.join(ENV['USERPROFILE'] || Dir.home, 'grokbot-mcp-bridge', 'export'), 'grouping_probe.json'))
