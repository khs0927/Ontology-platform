# frozen_string_literal: true
# 옹벽(직벽 + 기초). 예: retaining_wall(path: [[0,0],[30000,0]], base: -2500, height: 5000, thk: 300)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def retaining_wall(path:, base:, height:, thk: 300, footing: [1500, 400], level: 'GL', name: nil)
    op('retaining_wall') do
      g = model.active_entities.add_group
      path.each_cons(2) do |a, b|
        len = Math.hypot(b[0] - a[0], b[1] - a[1])
        s = g.entities.add_group
        box(s.entities, 0, 0, 0, len, thk, height)
        box(s.entities, 0, -(footing[0] - thk) / 2.0, -footing[1], len, footing[0], footing[1]) if footing
        s.transform!(Geom::Transformation.translation(pt(a[0], a[1], base)) *
                     Geom::Transformation.rotation(ORIGIN, Z_AXIS, Math.atan2(b[1] - a[1], b[0] - a[0])))
      end
      nm = name || 'RW'
      stamp(g, cls: 'retaining-wall', asset_id: asset_id('retaining-wall', nm), name: nm, level: level,
               extra: { 'height_mm' => height, 'thk_mm' => thk })
    end
  end
end
