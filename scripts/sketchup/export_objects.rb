# Read-only hierarchy + per-object export. Never edits entities/tags/names.
require 'json'; require 'digest'
module GrokEx
  OUT=(ENV['SION_SU_OUT'] || File.join(Dir.home,'su','out')).tr('\\','/')
  BLOCK=%w[tree person furniture planter vehicle imported-3d counter-millwork]
  def self.mm(v); (v.to_f*25.4).round(1); end
  def self.s(v); x=v.to_s.dup.force_encoding('UTF-8'); x.valid_encoding? ? x : x.encode('UTF-8',invalid: :replace,undef: :replace,replace:'?'); end
  def self.safe(n); s(n).gsub(/[\\\/:*?"<>|#~\s]+/,'_')[0,60]; end
  def self.wbb(df,tr); b=df.bounds; return nil if b.empty?; nb=Geom::BoundingBox.new; (0..7).each{|i| nb.add(b.corner(i).transform(tr))}; {'min'=>nb.min.to_a.map{|v|mm(v)},'max'=>nb.max.to_a.map{|v|mm(v)},'size'=>[mm(nb.width),mm(nb.height),mm(nb.depth)]}; end
  def self.run
    m=Sketchup.active_model; t0=Time.now; mod0=m.modified?
    cls={}; JSON.parse(File.read(OUT+'/../classification.json',encoding:'UTF-8'))['assignments'].each{|a| cls[a['definition']]=a['class']}
    rec={} # def -> [faces,edges] recursive
    cnt=lambda{|df| rec[df] ||= begin f=0;e=0; df.entities.each{|x| if x.is_a?(Sketchup::Face) then f+=1 elsif x.is_a?(Sketchup::Edge) then e+=1 elsif x.respond_to?(:definition) then r=cnt.call(x.definition); f+=r[0]; e+=r[1] end}; [f,e] end}
    nodes=[]; walk=nil
    walk=lambda{|ents,tr,depth,ppid,path,inblock|
      ents.each{|e| next unless e.is_a?(Sketchup::Group)||e.is_a?(Sketchup::ComponentInstance)
        df=e.definition; wt=tr*e.transformation; label=e.name.to_s.empty? ? df.name : e.name; np=path+[s(label)]
        c=cls[df.name]; blk=BLOCK.include?(c)
        cc=Hash.new(0); df.entities.each{|x| cc[x.typename]+=1}; r=cnt.call(df)
        nodes << {'pid'=>e.persistent_id,'entityID'=>e.entityID,'parent_pid'=>ppid,'depth'=>depth,'type'=>e.typename,'name'=>s(e.name),'definition'=>s(df.name),
          'definition_instances'=>df.instances.size,'path'=>np.join(' > '),'tag'=>(e.layer ? s(e.layer.name) : nil),'material'=>(e.material ? s(e.material.name) : nil),
          'transformation'=>e.transformation.to_a.map{|v| v.round(5)},'world_bbox'=>wbb(df,wt),'child_counts'=>cc,'faces_recursive'=>r[0],'edges_recursive'=>r[1],
          'class_guess'=>c,'block_node'=>blk,'inside_block'=>inblock}
        walk.call(df.entities,wt,depth+1,e.persistent_id,np,inblock||blk) if depth<12 }}
    walk.call(m.entities,Geom::Transformation.new,0,nil,[],false)
    File.write(OUT+'/hierarchy.json',JSON.pretty_generate({'model'=>s(m.path),'modified_before'=>mod0,'nodes'=>nodes}),encoding:'UTF-8')
    # exports: depth<=2 non-inside-block nodes, plus every block node; one file per definition
    done={}; man=[]; fails=[]
    nodes.each{|n| next if n['inside_block']; next unless n['depth']<=2 || n['block_node']
      df=m.definitions[n['definition']]; next unless df
      cl=n['class_guess']||'unclassified'; dir="#{OUT}/objects/#{cl}"; Dir.mkdir(OUT+'/objects') rescue nil; Dir.mkdir(dir) rescue nil
      f=done[df] || "#{dir}/#{safe(df.name)}__#{n['pid']}.skp"; err=nil
      unless done[df]
        begin; ok=df.save_as(f); err='save_as returned false' unless ok; rescue => ex; err=ex.message; end
        if err then fails << {'pid'=>n['pid'],'definition'=>n['definition'],'error'=>s(err)}; f=nil else done[df]=f; (df.save_thumbnail(f.sub(/\.skp$/,'.png')) rescue nil) if (Time.now-t0)<1500 end
      end
      man << {'id'=>"su:#{n['pid']}",'pid'=>n['pid'],'path'=>n['path'],'depth'=>n['depth'],'type'=>n['type'],'definition'=>n['definition'],'class_guess'=>n['class_guess'],'block_node'=>n['block_node'],'file'=>f,'bbox'=>n['world_bbox'],'tag'=>n['tag'],'material'=>n['material']} }
    File.write(OUT+'/objects.json',JSON.pretty_generate({'objects'=>man,'failures'=>fails}),encoding:'UTF-8')
    "ok nodes=#{nodes.size} exported_files=#{done.size} manifest=#{man.size} fails=#{fails.size} modified_before=#{mod0} after=#{m.modified?} t=#{(Time.now-t0).round}"
  end
end
GrokEx.run
