# frozen_string_literal: true
# 자산 라이브러리에서 asset_id로 블럭 배치(나무·사람·가구 = 블럭 1개로 기억).
# library: 'G:/내 드라이브/SketchUp-Assets/ontology-objects/0914-meeting' 아래 index.json({asset_id: {path, class}}) 또는 직접 경로.
require 'json'
require_relative 'sion_bim_common'
module SionBim
  module_function
  def place_block(asset_id:, library:, at:, rot: 0, scale: 1.0, tag_name: nil, level: '1 FL')
    idx_path = File.join(library, 'index.json')
    entry = File.exist?(idx_path) ? JSON.parse(File.read(idx_path, encoding: 'UTF-8'))[asset_id] : nil
    path = entry ? File.join(library, entry['path']) : File.join(library, "#{asset_id}.skp")
    raise "asset not found: #{asset_id}" unless File.exist?(path)
    op('place_block') do
      defn = model.definitions.load(path)
      tr = Geom::Transformation.translation(pt(*at)) *
           Geom::Transformation.rotation(ORIGIN, Z_AXIS, rot.degrees) *
           Geom::Transformation.scaling(scale)
      inst = model.active_entities.add_instance(defn, tr)
      stamp(inst, cls: 'asset-block', asset_id: asset_id, name: defn.name, level: level,
                  extra: { 'source_class' => entry && entry['class'], 'path' => File.basename(path) })
      inst.layer = tag(tag_name) if tag_name
      inst
    end
  end
end
