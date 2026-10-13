# frozen_string_literal: true
# 슬래브. outline: [[x,y],...] mm, top: 상단 레벨 mm. 예: slab(outline: [[0,0],[25700,0],[25700,27300],[0,27300]], top: 10200, thk: 160)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def slab(outline:, top:, thk: 200, level: '2 FL', name: nil)
    op('slab') do
      g = model.active_entities.add_group
      f = g.entities.add_face(outline.map { |x, y| pt(x, y, top - thk) })
      f.reverse! if f.normal.z.negative?
      f.pushpull(mm(thk))
      nm = name || "SLAB-#{level}"
      stamp(g, cls: 'slab', asset_id: asset_id('slab', nm), name: nm, level: level, extra: { 'thk_mm' => thk, 'top_mm' => top })
    end
  end
end
