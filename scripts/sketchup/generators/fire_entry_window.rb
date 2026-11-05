# frozen_string_literal: true
# 소방관 진입창. 기준(참고): 피난방화규칙 제18조의2 — 유리 폭 900·높이 1000 이상, 바닥~창 하단 800 이내
# (난간 있는 노대등 1200), 붉은 역삼각형 지름 200 이상, 타격지점 원형 지름 30 이상. 값은 data/sources/sketchup/code-refs 참조.
# 판정은 참고용 경고일 뿐이며 실제 적합성은 원문·관할 검토로 확인해야 한다.
require_relative 'window'
module SionBim
  module_function
  FIRE_MIN = { glass_w: 900, glass_h: 1000, sill: 800, sill_balcony: 1200, tri: 200, strike: 30 }.freeze

  def fire_entry_checks(width:, height:, sill:, frame:, balcony:)
    gw = width - 2 * frame
    gh = height - 2 * frame
    lim = balcony ? FIRE_MIN[:sill_balcony] : FIRE_MIN[:sill]
    { 'glass_width' => gw >= FIRE_MIN[:glass_w], 'glass_height' => gh >= FIRE_MIN[:glass_h], 'sill' => sill <= lim }
  end

  def fire_entry_window(origin:, base:, width: 1200, height: 1300, sill: 700, frame: 50, depth: 70,
                        glass: 'tempered-5', glass_thk: 5, balcony: false, facing: 'S', level: '2 FL', host: nil, name: nil)
    chk = fire_entry_checks(width: width, height: height, sill: sill, frame: frame, balcony: balcony)
    chk.each { |k, ok| warn "[sion] 소방관 진입창 #{k} 기준 미달 추정 — 법규 확인 필요" unless ok }
    op('fire_entry_window') do
      g = model.active_entities.add_group
      gl = build_window_frame(g.entities, width, height, frame: frame, depth: depth, mullions: 0, transoms: 0, glass_thk: glass_thk)
      # 표시: 중앙 붉은 역삼각형(외접원 지름 FIRE_MIN[:tri]+) / 모서리 타격지점 원(지름 FIRE_MIN[:strike]+)
      mark = g.entities.add_group
      r = FIRE_MIN[:tri] / 2.0 + 10
      cx = width / 2.0
      cz = height / 2.0
      yf = -1.0
      pts = [[cx - r * Math.sin(Math::PI / 3), yf, cz + r / 2.0], [cx + r * Math.sin(Math::PI / 3), yf, cz + r / 2.0], [cx, yf, cz - r]]
      mark.entities.add_face(pts.map { |p| pt(*p) })
      circ = mark.entities.add_circle(pt(frame + 40, yf, frame + 40), Y_AXIS, mm(FIRE_MIN[:strike] / 2.0 + 5), 16)
      mark.entities.add_face(circ)
      mark.material = material('ZIUM-FIRE-RED')
      mark.name = 'FIRE-MARK'
      place_opening(g, origin: origin, base: base, sill: sill, facing: facing)
      nm = name || "WIN-FIRE-#{level}"
      stamp(g, cls: 'fire-entry-window', asset_id: asset_id('fire-entry-window', nm), name: nm, level: level, extra: {
        'width_mm' => width, 'height_mm' => height, 'sill_height_mm' => sill, 'head_height_mm' => sill + height,
        'frame_depth_mm' => depth, 'glass_type' => glass, 'glass_thickness_mm' => glass_thk, 'operation_type' => 'fixed',
        'orientation' => facing, 'wall_host' => host, 'fire_entry_window' => true, 'balcony' => balcony,
        'ifc_predefined_type' => 'WINDOW', 'code_ref' => 'kr-fire-entry-window',
        'compliance_estimate' => chk.values.all? ? 'pass-estimated' : 'fail-estimated', 'review_state' => 'unverified'
      })
      g
    end
  end
end
