# frozen_string_literal: true
# 다단 주차데크 한 단(+주차면 선). 예(0914): parking_deck(x0:0,y0:0,w:30000,d:16000,base:500, stalls:8)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def parking_deck(x0:, y0:, w:, d:, base:, thk: 250, stalls: 0, stall_w: 2500, stall_d: 5000, tier: 1, name: nil)
    op('parking_deck') do
      g = model.active_entities.add_group
      box(g.entities, x0, y0, base - thk, w, d, thk)
      (0..stalls).each do |i|
        x = x0 + i * stall_w
        break if x > x0 + w
        g.entities.add_line(pt(x, y0, base + 1), pt(x, y0 + stall_d, base + 1))
      end
      nm = name || "PK-T#{tier}"
      stamp(g, cls: 'parking-deck', asset_id: asset_id('parking-deck', nm), name: nm, level: "PK #{base}",
               extra: { 'tier' => tier, 'stalls' => stalls })
    end
  end
end
