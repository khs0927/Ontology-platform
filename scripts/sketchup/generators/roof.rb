# frozen_string_literal: true
# 처마 있는 평(경사)지붕. overhang: {w:,e:,s:,n:} mm. 예(0914): roof(x0:0,y0:0,w:22000,d:21800, base:14600, overhang:{w:1800,s:1400,e:700,n:0}, slope_deg:5.9)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def roof(x0:, y0:, w:, d:, base:, thk: 300, overhang: {}, slope_deg: 0, level: 'RF', name: nil)
    o = { w: 0, e: 0, s: 0, n: 0 }.merge(overhang)
    op('roof') do
      g = model.active_entities.add_group
      box(g.entities, x0 - o[:w], y0 - o[:s], 0, w + o[:w] + o[:e], d + o[:s] + o[:n], thk)
      tr = Geom::Transformation.translation(pt(0, 0, base))
      tr *= Geom::Transformation.rotation(pt(x0, y0, 0), X_AXIS, slope_deg.degrees) unless slope_deg.zero?
      g.transform!(tr)
      nm = name || "ROOF-#{level}"
      stamp(g, cls: 'roof', asset_id: asset_id('roof', nm), name: nm, level: level,
               extra: { 'slope_deg' => slope_deg, 'overhang_mm' => o.map { |k, v| "#{k}=#{v}" }.join(',') })
    end
  end
end
