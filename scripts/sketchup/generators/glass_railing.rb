# frozen_string_literal: true
# 유리난간. 기본 높이 1200(법규 확인용 기준). 예: glass_railing(path: [[0,0],[8000,0]], base: 10200)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def glass_railing(path:, base:, height: 1200, thk: 24, cap: true, level: '2 FL', name: nil)
    warn "[sion] 난간 높이 #{height} < 1200 — 법규 확인 필요" if height < 1200
    op('glass_railing') do
      g = model.active_entities.add_group
      path.each_cons(2).with_index do |(a, b), i|
        len = Math.hypot(b[0] - a[0], b[1] - a[1])
        s = g.entities.add_group
        box(s.entities, 0, -thk / 2.0, 0, len, thk, height)
        box(s.entities, 0, -25, height, len, 50, 40) if cap
        s.transform!(Geom::Transformation.translation(pt(a[0], a[1], base)) *
                     Geom::Transformation.rotation(ORIGIN, Z_AXIS, Math.atan2(b[1] - a[1], b[0] - a[0])))
        s.name = "GR-SEG#{i}"
      end
      nm = name || "GR-#{level}"
      stamp(g, cls: 'glass-railing', asset_id: asset_id('glass-railing', nm), name: nm, level: level, extra: { 'height_mm' => height })
    end
  end
end
