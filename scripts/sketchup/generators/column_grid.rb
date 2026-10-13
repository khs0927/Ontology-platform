# frozen_string_literal: true
# 기둥 그리드. 예(0914): column_grid(xs: [70273.7], ys_spacing: [5900,10500,5100], y0: 22505, base: 5000, height: 4200, dia: 480)
require_relative 'sion_bim_common'
module SionBim
  module_function
  def column_grid(xs:, ys_spacing:, y0: 0, base: 0, height: 4200, dia: 480, level: '1 FL', prefix: 'C')
    ys = ys_spacing.each_with_object([y0]) { |s, a| a << a.last + s }
    op('column_grid') do
      parent = model.active_entities.add_group
      xs.each_with_index do |x, i|
        ys.each_with_index do |y, j|
          g = parent.entities.add_group
          c = g.entities.add_circle(pt(x, y, base), Z_AXIS, mm(dia / 2.0), 24)
          g.entities.add_face(c).tap { |f| f.reverse! if f.normal.z.negative? }.pushpull(mm(height))
          stamp(g, cls: 'column', asset_id: asset_id('column', "#{prefix}#{i + 1}-#{j + 1}"),
                   name: "#{prefix}#{i + 1}-#{j + 1}", level: level, extra: { 'dia_mm' => dia, 'height_mm' => height })
        end
      end
      parent.name = "STR-COL-#{level}"
      parent
    end
  end
end
