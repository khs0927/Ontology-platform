# frozen_string_literal: true
# 일반 창(프레임+유리, 멀리언/트랜섬 분할). 벽면 기준 로컬 좌표: x=폭, z=높이, y=벽두께 방향.
# 예: window(origin: [80000, 12000], base: 10200, width: 1800, height: 1500, sill: 900, mullions: 1, operation: 'sliding', facing: 'S')
require_relative 'sion_bim_common'
module SionBim
  module_function
  OPERATIONS = %w[fixed casement sliding tilt tilt-turn awning].freeze
  # IFC 4.3 IfcWindowTypePartitioningEnum 근사
  def window_partitioning(mullions, transoms)
    return 'SINGLE_PANEL' if mullions.zero? && transoms.zero?
    return "DOUBLE_PANEL_#{transoms.zero? ? 'VERTICAL' : 'HORIZONTAL'}" if mullions + transoms == 1
    return "TRIPLE_PANEL_#{transoms.zero? ? 'VERTICAL' : 'HORIZONTAL'}" if (mullions == 2 && transoms.zero?) || (transoms == 2 && mullions.zero?)
    'USERDEFINED'
  end

  def build_window_frame(ents, width, height, frame:, depth:, mullions:, transoms:, glass_thk:)
    box(ents, 0, 0, 0, width, depth, frame)                    # 하부
    box(ents, 0, 0, height - frame, width, depth, frame)       # 상부
    box(ents, 0, 0, 0, frame, depth, height)                   # 좌
    box(ents, width - frame, 0, 0, frame, depth, height)       # 우
    cw = (width - 2 * frame).to_f / (mullions + 1)
    ch = (height - 2 * frame).to_f / (transoms + 1)
    (1..mullions).each { |i| box(ents, frame + cw * i - frame / 2.0, 0, 0, frame, depth, height) }
    (1..transoms).each { |j| box(ents, 0, 0, frame + ch * j - frame / 2.0, width, depth, frame) }
    gl = ents.add_group
    box(gl.entities, frame, (depth - glass_thk) / 2.0, frame, width - 2 * frame, glass_thk, height - 2 * frame)
    gl.material = material('ZIUM-GLASS')
    gl.name = 'GLASS'
    gl
  end

  def place_opening(g, origin:, base:, sill:, facing:)
    rot = { 'S' => 0, 'E' => 90, 'N' => 180, 'W' => 270 }.fetch(facing || 'S', 0)
    g.transform!(Geom::Transformation.translation(pt(origin[0], origin[1], base + sill)) *
                 Geom::Transformation.rotation(ORIGIN, Z_AXIS, rot.degrees))
  end

  def window(origin:, base:, width:, height:, sill: 900, frame: 60, depth: 70, mullions: 0, transoms: 0,
             operation: 'fixed', glass: 'pair-24', glass_thk: 24, facing: 'S', level: '1 FL', host: nil, name: nil)
    raise ArgumentError, "operation #{operation}" unless OPERATIONS.include?(operation)
    op('window') do
      g = model.active_entities.add_group
      build_window_frame(g.entities, width, height, frame: frame, depth: depth, mullions: mullions, transoms: transoms, glass_thk: glass_thk)
      place_opening(g, origin: origin, base: base, sill: sill, facing: facing)
      nm = name || "WIN-#{width}x#{height}"
      stamp(g, cls: 'window', asset_id: asset_id('window', nm), name: nm, level: level, extra: {
        'width_mm' => width, 'height_mm' => height, 'sill_height_mm' => sill, 'head_height_mm' => sill + height,
        'frame_depth_mm' => depth, 'glass_type' => glass, 'operation_type' => operation,
        'mullions' => mullions, 'transoms' => transoms, 'orientation' => facing, 'wall_host' => host,
        'ifc_predefined_type' => 'WINDOW', 'ifc_partitioning_type' => window_partitioning(mullions, transoms)
      })
    end
  end
end
