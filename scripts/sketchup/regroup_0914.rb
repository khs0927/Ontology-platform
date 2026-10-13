# frozen_string_literal: true
# regroup_0914.rb — 0914_담당미팅 재그룹화 (docs/sketchup/0914-REGROUP-PLAN.ko.md)
#
# SketchUp 2022(Ruby 2.7) 호환. 기본은 읽기 전용: DRY_RUN = true 이면 계획만 출력하고 모델을 바꾸지 않습니다.
# DRY_RUN = false 이면 model.start_operation 하나로 묶여 Ctrl+Z 한 번에 되돌릴 수 있습니다.
# 반드시 원본을 따로 저장한 뒤 실행하세요. 대상은 persistent_id(pid)로 찾습니다.
module ZiumRegroup0914
  DRY_RUN         = true
  APPLY_TAGS      = true
  APPLY_LEVELS    = true   # BLDG-1F/2F/RF 컨테이너 생성 및 이동
  APPLY_NAMES     = false  # /review 확정 후 true
  FIX_INNER_TAGS  = false  # 형상 안 CAD 태그 → Layer0
  PURGE           = false  # 사람 확인 후에만 true

  MM = 1.0 / 25.4 # inch per mm

  LEVELS = [
    { key: '1F', name: 'BLDG-1F', label: '1 FL +5000',    z: 5000 },
    { key: '2F', name: 'BLDG-2F', label: '2 FL +10200',   z: 10200 },
    { key: 'RF', name: 'BLDG-RF', label: 'RF TOS +14600', z: 14600 }
  ].freeze

  TOP_TAGS = {
    30598 => 'CAD-참조', 47944 => '@stair', 90359 => '옹벽',
    125087 => '@3D-대지', 125433 => '@3D-대지', 1245541 => '@3D-대지', 1245859 => '@3D-대지',
    800070 => 'Trees 3D', 511546 => 'A-본동', 1458557 => 'A-별동',
    1171922 => 'S-STEEL COLUMN', 2004749 => 'S-STEEL COLUMN', 2004982 => 'S-STEEL COLUMN',
    2005214 => 'S-STEEL COLUMN', 2005446 => 'S-STEEL COLUMN',
    1181414 => '@win', 1249504 => 'WIP', 1249528 => 'WIP'
  }.freeze

  TOP_NAMES = {
    30598 => 'SITE-CAD-학장동', 47944 => 'SITE-외부계단', 90359 => 'SITE-옹벽',
    125087 => 'SITE-조경-동측', 125433 => 'SITE-포장', 800070 => 'SITE-수목',
    511546 => 'BLDG-본동', 1458557 => 'BLDG-별동', 1171922 => 'STR-보',
    1249504 => 'WIP-0818-표식-1', 1249528 => 'WIP-0818-표식-2'
  }.freeze

  # 그룹#201 직계 자식 → 층 (하단 Z 기준). 그룹#202(4577802)는 분해 대상.
  BLDG_201 = 511546
  EXPLODE_202 = 4577802
  BLDG_105_WRAPPER = 4905257 # 그룹#160
  TREE_PROXY = [800070, 4577839, 4577840, 4577841].freeze
  INNER_CAD_TAGS = ['도로계획', 'XCLINE', '@0818변경', '@win'].freeze

  module_function

  def log(msg)
    puts("[regroup_0914#{DRY_RUN ? ' DRY' : ''}] #{msg}")
  end

  def find(model, pid)
    e = model.find_entity_by_persistent_id(pid)
    log("  ! pid #{pid} 없음 — 건너뜀") unless e
    e
  end

  def label(e)
    "#{e.typename} '#{e.name}' def=#{e.definition.name} (pid #{e.persistent_id})"
  end

  def level_for(e)
    zmin = e.bounds.min.z / MM
    return LEVELS[2] if zmin >= 14600 - 50
    return LEVELS[1] if zmin >= 10200 - 450 # 2층 걸침(9150~) 포함은 수동 검토
    LEVELS[0]
  end

  def ensure_tag(model, name)
    model.layers[name] || (DRY_RUN ? nil : model.layers.add(name))
  end

  def step_tags(model)
    log('== 1. 최상위 태그 지정')
    TOP_TAGS.each do |pid, tag|
      e = find(model, pid) or next
      log("  #{label(e)}: #{e.layer.name} → #{tag}")
      e.layer = ensure_tag(model, tag) unless DRY_RUN
    end
    cad = find(model, 30598)
    if cad
      log('  학장동 CAD 잠금')
      cad.locked = true unless DRY_RUN
    end
  end

  def step_names(model)
    log("== 2. 최상위 이름#{APPLY_NAMES ? '' : ' (APPLY_NAMES=false: 출력만)'}")
    TOP_NAMES.each do |pid, nm|
      e = find(model, pid) or next
      log("  #{label(e)} → #{nm}")
      e.name = nm if !DRY_RUN && APPLY_NAMES
    end
  end

  def move_into(container, inst)
    t = container.transformation.inverse * inst.transformation
    copy = container.entities.add_instance(inst.definition, t)
    copy.name = inst.name
    copy.layer = inst.layer
    copy.material = inst.material
    inst.erase!
    copy
  end

  def step_levels(model)
    log('== 3. 그룹#201 층 컨테이너 (BLDG-1F/2F/RF)')
    bldg = find(model, BLDG_201) or return
    ents = bldg.definition.entities
    g202 = find(model, EXPLODE_202)
    if g202
      log("  explode #{label(g202)} → 자식(#203/#205/#207)을 층으로 배정")
      g202.explode unless DRY_RUN
    end
    containers = {}
    LEVELS.each do |lv|
      log("  컨테이너 #{lv[:name]} (#{lv[:label]}) 원점 Z=#{lv[:z]}")
      next if DRY_RUN
      g = ents.add_group
      g.transformation = Geom::Transformation.translation([0, 0, lv[:z] * MM])
      g.name = lv[:name]
      g.set_attribute('zium/level', 'name', lv[:label])
      g.set_attribute('zium/level', 'z_mm', lv[:z])
      containers[lv[:key]] = g
    end
    kids = ents.grep(Sketchup::Group) + ents.grep(Sketchup::ComponentInstance)
    kids.reject! { |k| LEVELS.any? { |lv| k.name == lv[:name] } }
    kids.each do |k|
      lv = level_for(k)
      log("  #{label(k)} zmin=#{(k.bounds.min.z / MM).round} → #{lv[:name]}")
      move_into(containers[lv[:key]], k) unless DRY_RUN
    end
    # 빈 그룹 컨테이너는 SketchUp이 지우므로 DRY_RUN 아닐 때만 의미 있음
  end

  def step_105(model)
    log('== 4. 그룹#105 래퍼(그룹#160) 분해')
    w = find(model, BLDG_105_WRAPPER) or return
    log("  explode #{label(w)}")
    w.explode unless DRY_RUN
  end

  def step_inner_tags(model)
    log("== 5. 형상 안 CAD 태그 → Layer0#{FIX_INNER_TAGS ? '' : ' (출력만)'}")
    l0 = model.layers[0]
    model.definitions.each do |d|
      next if d.image?
      n = d.entities.count { |e| INNER_CAD_TAGS.include?(e.layer.name) && !e.is_a?(Sketchup::ComponentInstance) && !e.is_a?(Sketchup::Group) }
      next if n.zero?
      log("  #{d.name}: #{n}개")
      next if DRY_RUN || !FIX_INNER_TAGS
      d.entities.each { |e| e.layer = l0 if INNER_CAD_TAGS.include?(e.layer.name) && !(e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)) }
    end
  end

  def step_trees(model)
    log('== 6. 수목 프록시 대상 (교체는 사람이 확인)')
    TREE_PROXY.each do |pid|
      e = find(model, pid) or next
      faces = 0
      walk = lambda { |ents| ents.each { |x| faces += 1 if x.is_a?(Sketchup::Face); walk.call(x.definition.entities) if x.respond_to?(:definition) } }
      walk.call(e.definition.entities)
      log("  #{label(e)} 면 #{faces} → 프록시(≤100)")
    end
  end

  def step_purge(model)
    log("== 7. purge 후보#{PURGE ? '' : ' (PURGE=false: 출력만)'}")
    unused = model.definitions.reject { |d| d.image? || d.instances.any? }
    log("  미사용 정의 #{unused.size}개: #{unused.first(15).map(&:name).join(', ')}#{unused.size > 15 ? ' …' : ''}")
    auto = model.materials.select { |m| m.name.start_with?('<auto>') }
    log("  <auto> 재질 #{auto.size}개")
    used_layers = {}
    model.definitions.each { |d| d.entities.each { |e| used_layers[e.layer] = true } }
    model.entities.each { |e| used_layers[e.layer] = true }
    empty = model.layers.reject { |l| l == model.layers[0] || used_layers[l] || l.name == 'LIBFREDO6_TEMP_LAYER' }
    log("  빈 태그(현재 기준) #{empty.size}개: #{empty.map(&:name).join(', ')}")
    return if DRY_RUN || !PURGE
    model.definitions.purge_unused
    model.materials.purge_unused
    model.layers.purge_unused
  end

  def run
    model = Sketchup.active_model
    log("모델: #{model.title}  DRY_RUN=#{DRY_RUN}")
    model.start_operation('Zium regroup 0914', true) unless DRY_RUN
    begin
      step_tags(model) if APPLY_TAGS
      step_names(model)
      step_levels(model) if APPLY_LEVELS
      step_105(model)
      step_inner_tags(model)
      step_trees(model)
      step_purge(model)
      model.commit_operation unless DRY_RUN
      log(DRY_RUN ? '완료: 변경 없음(계획만 출력)' : '완료: Ctrl+Z 한 번으로 되돌릴 수 있습니다')
    rescue StandardError => e
      model.abort_operation unless DRY_RUN
      log("오류로 중단, 변경 취소: #{e.class}: #{e.message}")
      raise
    end
  end
end

ZiumRegroup0914.run
