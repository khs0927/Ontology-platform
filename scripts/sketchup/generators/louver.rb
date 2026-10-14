# frozen_string_literal: true
# 루버(살 배열). direction: 'horizontal'(수평 살, 높이 방향 배열) | 'vertical'(수직 살, 폭 방향 배열)
# 예: louver(origin: [80000, 12000], base: 5000, width: 3000, height: 2400, blade_w: 150, blade_t: 30, pitch: 200, angle: 30)
require_relative 'sion_bim_common'
module SionBim
  module_function

  def louver(origin:, base:, width:, height:, blade_w: 150, blade_t: 30, pitch: 200, angle: 0,
             direction: 'horizontal', sill: 0, material_name: 'ZIUM-MULLION', facing: 'S', level: '1 FL', host: nil, name: nil)
    raise ArgumentError, 'pitch must be > 0' unless pitch.positive?
    op('louver') do
      g = model.active_entities.add_group
      span = direction == 'horizontal' ? height : width
      n = (span / pitch.to_f).floor + 1
      n.times do |i|
        s = g.entities.add_group
        if direction == 'horizontal'
          box(s.entities, 0, -blade_w / 2.0, -blade_t / 2.0, width, blade_w, blade_t)
          s.transform!(Geom::Transformation.translation(pt(0, 0, i * pitch)) *
                       Geom::Transformation.rotation(ORIGIN, X_AXIS, angle.degrees))
        else
          box(s.entities, -blade_t / 2.0, -blade_w / 2.0, 0, blade_t, blade_w, height)
          s.transform!(Geom::Transformation.translation(pt(i * pitch, 0, 0)) *
                       Geom::Transformation.rotation(ORIGIN, Z_AXIS, angle.degrees))
        end
        s.name = "LV-BLADE#{i}"
      end
      g.material = material(material_name)
      rot = { 'S' => 0, 'E' => 90, 'N' => 180, 'W' => 270 }.fetch(facing, 0)
      g.transform!(Geom::Transformation.translation(pt(origin[0], origin[1], base + sill)) *
                   Geom::Transformation.rotation(ORIGIN, Z_AXIS, rot.degrees))
      nm = name || "LOUVER-#{direction[0].upcase}-#{width}x#{height}"
      stamp(g, cls: 'louver', asset_id: asset_id('louver', nm), name: nm, level: level, extra: {
        'width_mm' => width, 'height_mm' => height, 'blade_width_mm' => blade_w, 'blade_thickness_mm' => blade_t,
        'pitch_mm' => pitch, 'angle_deg' => angle, 'direction' => direction, 'blade_count' => n,
        'orientation' => facing, 'wall_host' => host, 'ifc_entity' => 'IfcShadingDevice', 'ifc_predefined_type' => 'LOUVER'
      })
    end
  end
end
