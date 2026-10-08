# Renders PNGs of the current view and of each scene's camera, then restores the user's camera.
# Read-only on model data: no geometry, page, layer or style is changed.
module GrokViews
  def self.run(dir)
    m = Sketchup.active_model
    v = m.active_view
    c = v.camera
    saved = Sketchup::Camera.new(c.eye, c.target, c.up, c.perspective?, c.perspective? ? c.fov : 35.0)
    saved.height = c.height unless c.perspective?
    out = []
    shot = lambda do |name|
      path = File.join(dir, name)
      v.write_image(filename: path, width: 1600, height: 1000, antialias: true, transparent: false)
      out << name
    end
    begin
      shot.call('view_current.png')
      m.pages.each_with_index do |pg, i|
        pc = pg.camera
        v.camera = Sketchup::Camera.new(pc.eye, pc.target, pc.up, pc.perspective?, pc.perspective? ? pc.fov : 35.0)
        shot.call("view_scene#{i + 1}.png")
      end
      bb = m.bounds
      ctr = bb.center
      d = bb.diagonal
      v.camera = Sketchup::Camera.new(Geom::Point3d.new(ctr.x - d, ctr.y - d, ctr.z + d * 0.8), ctr, Z_AXIS, true, 35.0)
      v.zoom_extents
      shot.call('view_iso_sw.png')
      top = Sketchup::Camera.new(Geom::Point3d.new(ctr.x, ctr.y, ctr.z + d * 2), ctr, Y_AXIS, false)
      v.camera = top
      v.zoom_extents
      shot.call('view_top.png')
    ensure
      v.camera = saved
      v.invalidate
    end
    "ok #{out.join(',')}"
  end
end
# Output dir: $SION_SU_EXPORT_DIR, else %USERPROFILE%/grokbot-mcp-bridge/export (must exist).
GrokViews.run(ENV['SION_SU_EXPORT_DIR'] || File.join(ENV['USERPROFILE'] || Dir.home, 'grokbot-mcp-bridge', 'export'))
