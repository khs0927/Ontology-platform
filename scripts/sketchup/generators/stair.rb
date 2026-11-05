# frozen_string_literal: true
# 직선 계단. 단높이는 rise/단수로 자동. 예(0914 외부): stair(origin: [0,0], base: 0, rise: 5000, width: 2400, riser_max: 170)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def stair(origin:, base:, rise:, width: 1200, riser_max: 170, tread: 300, dir_deg: 0, level: '1 FL', name: nil)
    n = (rise.to_f / riser_max).ceil
    r = rise.to_f / n
    op('stair') do
      g = model.active_entities.add_group
      n.times { |i| box(g.entities, i * tread, 0, i * r, tread, width, r) }
      g.transform!(Geom::Transformation.translation(pt(origin[0], origin[1], base)) *
                   Geom::Transformation.rotation(ORIGIN, Z_AXIS, dir_deg.degrees))
      nm = name || "ST-#{level}"
      stamp(g, cls: 'stair', asset_id: asset_id('stair', nm), name: nm, level: level,
               extra: { 'risers' => n, 'riser_mm' => r.round(1), 'tread_mm' => tread, 'width_mm' => width })
    end
  end
end
