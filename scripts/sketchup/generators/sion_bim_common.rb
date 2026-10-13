# frozen_string_literal: true
# 공통 헬퍼: 지음(zium) 태그·레벨 규칙 + 'sion_bim' 속성 사전.
# SketchUp 안에서만 실행. 모든 입력 단위는 mm.
module SionBim
  DICT = 'sion_bim'
  ZIUM_DICT = 'zium'
  # 클래스 → [지음 태그, IFC 엔터티, 기본 재질]
  CLASS_MAP = {
    'column'          => ['COL',   'IfcColumn',       '노출콘크리트'],
    'slab'            => ['COL',   'IfcSlab',         '노출콘크리트'],
    'curtain-wall'    => ['WIN',   'IfcCurtainWall',  'ZIUM-GLASS'],
    'mullion'         => ['WIN',   'IfcMember',       'ZIUM-MULLION'],
    'glass-railing'   => ['STL',   'IfcRailing',      'ZIUM-GLASS'],
    'stair'           => ['STAIR', 'IfcStair',        '노출콘크리트'],
    'retaining-wall'  => ['COL',   'IfcWall',         '노출콘크리트'],
    'roof'            => ['COL',   'IfcRoof',         'ZIUM-ROOF'],
    'parking-deck'    => ['ETC',   'IfcSlab',         '아스팔트'],
    'asset-block'     => ['FUR',   'IfcFurnishingElement', nil]
  }.freeze

  module_function

  def model = Sketchup.active_model
  def mm(v) = v.to_f.mm
  def pt(x, y, z = 0) = Geom::Point3d.new(mm(x), mm(y), mm(z))

  def tag(name) = model.layers[name] || model.layers.add(name)

  def material(name)
    return nil if name.nil?
    model.materials[name] || model.materials.add(name)
  end

  # 모든 생성기는 이 블록 안에서 작업 → Ctrl+Z 한 번으로 되돌림
  def op(title)
    model.start_operation("SION #{title}", true)
    r = yield
    model.commit_operation
    r
  rescue StandardError
    model.abort_operation
    raise
  end

  def stamp(ent, cls:, asset_id:, name:, level: nil, extra: {})
    tag_name, ifc, mat = CLASS_MAP.fetch(cls)
    ent.name = name
    ent.layer = tag(tag_name)
    ent.material = material(mat) if mat && ent.respond_to?(:material=)
    { 'asset_id' => asset_id, 'class' => cls, 'ifc' => ifc, 'tag' => tag_name,
      'level' => level, 'schema' => 'sion-bim/1' }.merge(extra).each do |k, v|
      ent.set_attribute(DICT, k, v) unless v.nil?
    end
    ent.set_attribute(ZIUM_DICT, 'kind', cls)
    ent
  end

  def box(ents, x, y, z, w, d, h)
    f = ents.add_face(pt(x, y, z), pt(x + w, y, z), pt(x + w, y + d, z), pt(x, y + d, z))
    f.reverse! if f.normal.z.negative?
    f.pushpull(mm(h))
    f
  end

  def asset_id(cls, name) = "0914:#{cls}:#{name}".downcase.gsub(/\s+/, '-')
end
