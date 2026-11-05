# frozen_string_literal: true
# 멀리언 커튼월. 예(0914 1F): curtain_wall(from: [0,0], to: [22500,0], base: 5000, height: 5000, module_w: 1500)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def curtain_wall(from:, to:, base:, height:, module_w: 1500, mullion: [50, 150], transom_at: [], glass_thk: 24, level: '1 FL', name: nil)
    dx = to[0] - from[0]; dy = to[1] - from[1]
    len = Math.hypot(dx, dy)
    n = [(len / module_w).ceil, 1].max
    op('curtain_wall') do
      g = model.active_entities.add_group
      e = g.entities
      # 로컬 좌표(X=벽 길이)로 만들고 마지막에 회전·이동
      glass = e.add_group
      box(glass.entities, 0, -glass_thk / 2.0, 0, len, glass_thk, height)
      stamp(glass, cls: 'curtain-wall', asset_id: asset_id('curtain-wall', 'glass'), name: 'CW-GLASS', level: level)
      mw, md = mullion
      (0..n).each do |i|
        x = [i * len / n - mw / 2.0, 0].max
        x = len - mw if x + mw > len
        m = e.add_group
        box(m.entities, x, -md / 2.0, 0, mw, md, height)
        stamp(m, cls: 'mullion', asset_id: asset_id('mullion', 'v'), name: "CW-MUL-V#{i}", level: level)
      end
      (transom_at + [0, height - mw]).each_with_index do |z, i|
        t = e.add_group
        box(t.entities, 0, -md / 2.0, z, len, md, mw)
        stamp(t, cls: 'mullion', asset_id: asset_id('mullion', 'h'), name: "CW-MUL-H#{i}", level: level)
      end
      tr = Geom::Transformation.translation(pt(from[0], from[1], base)) *
           Geom::Transformation.rotation(ORIGIN, Z_AXIS, Math.atan2(dy, dx))
      g.transform!(tr)
      nm = name || "CW-#{level}"
      stamp(g, cls: 'curtain-wall', asset_id: asset_id('curtain-wall', nm), name: nm, level: level,
               extra: { 'module_mm' => module_w, 'height_mm' => height, 'length_mm' => len.round })
    end
  end
end
