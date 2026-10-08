# Read-only geometry probe for selected definitions. Writes JSON; never modifies the model.
require 'json'
module GrokProbe
  NAMES = %w[그룹#19 그룹#23 그룹#112 그룹#113 그룹#111 그룹#3 그룹#4 그룹#31 그룹#9 그룹#8 그룹#259 그룹#57 그룹#83 그룹#27 그룹#21 그룹#24 그룹#16 그룹#29 그룹#35 그룹#34 그룹#6 그룹#14 그룹#11 그룹#45 col 그룹#133 그룹#203 그룹#213 그룹#204 그룹#219 그룹#223 그룹#134 그룹#246 그룹#247 그룹#245 그룹#257 그룹#99 그룹#115 그룹#124 그룹#88 그룹#225 그룹#89 C1 T T2 SO ch5 ch6 c3 그룹#163 그룹#61 그룹#155 그룹#54 그룹#63 그룹#74 Component#28 그룹#62 그룹167#1 그룹169#1 그룹#78 그룹#77 그룹#82 그룹#96 그룹#38 그룹#42 그룹#44 그룹#39 그룹#41 그룹#102 그룹#5 그룹#7 그룹#30 그룹#32 그룹#33 그룹#90 그룹#103 그룹#125 그룹#229 그룹#234 그룹#154 그룹#156 그룹#119 그룹#46 그룹#157 그룹#70 그룹#12 그룹#85 그룹#227 그룹#109 그룹#222 그룹#214 그룹#253 그룹#254 그룹#40 그룹#43]
  def self.mm(v); (v.to_f * 25.4).round(1); end
  def self.run(out)
    m = Sketchup.active_model
    res = {}
    NAMES.each do |n|
      df = m.definitions[n]
      next res[n] = nil unless df
      hz = Hash.new(0.0)
      slopes = Hash.new(0)
      vert = 0
      curves = 0
      arcs = 0
      df.entities.grep(Sketchup::Face).each do |f|
        nz = f.normal.z
        if nz.abs > 0.999
          z = mm(f.vertices.first.position.z).round
          hz[z] += f.area * 0.00064516
        elsif nz.abs < 0.001
          vert += 1
        else
          ang = (Math.acos(nz.abs) * 180 / Math::PI).round(1)
          slopes[ang] += 1
        end
      end
      seen = {}
      df.entities.grep(Sketchup::Edge).each do |e|
        c = e.curve
        next unless c
        next if seen[c.object_id]
        seen[c.object_id] = true
        curves += 1
        arcs += 1 if c.is_a?(Sketchup::ArcCurve)
      end
      radii = df.entities.grep(Sketchup::Edge).map(&:curve).compact.uniq.select { |c| c.is_a?(Sketchup::ArcCurve) }.map { |c| mm(c.radius) }.uniq.first(5)
      res[n] = { 'horizontal_z_area_m2' => hz.sort.map { |z, a| [z, a.round(3)] }.first(60), 'horizontal_levels' => hz.size,
                 'sloped_faces_by_angle_deg' => slopes.sort.first(20).to_h, 'vertical_faces' => vert,
                 'curves' => curves, 'arc_curves' => arcs, 'arc_radii_mm' => radii }
    end
    File.open(out, 'w:UTF-8') { |f| f.write(JSON.pretty_generate(res)) }
    "ok #{res.size}"
  end
end
# Output dir: $SION_SU_EXPORT_DIR, else %USERPROFILE%/grokbot-mcp-bridge/export (must exist).
GrokProbe.run(File.join(ENV['SION_SU_EXPORT_DIR'] || File.join(ENV['USERPROFILE'] || Dir.home, 'grokbot-mcp-bridge', 'export'), 'geom_probe.json'))
