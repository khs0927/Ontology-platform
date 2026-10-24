import ezdxf, sys
from ezdxf.addons import Importer
src = ezdxf.readfile(sys.argv[1]); out = sys.argv[2]
doc = ezdxf.new('R2018', setup=False); doc.units = 4; doc.header['$INSUNITS']=4; doc.header['$MEASUREMENT']=1
imp = Importer(src, doc)
imp.import_tables('*')
imp.import_block('ZIUM_sheet_architect')
ins = [e for e in src.modelspace().query('INSERT') if e.dxf.name=='ZIUM_sheet_architect'][0]
imp.finalize()
doc.modelspace().add_blockref('ZIUM_sheet_architect',(0,0),dxfattribs={'xscale':ins.dxf.xscale,'yscale':ins.dxf.yscale,'layer':ins.dxf.layer})
if len(sys.argv)>3:  # smoke sheet: 10x10m mass footprint at 1:100 inside sheet
    s = ins.dxf.xscale; msp = doc.modelspace()
    if '@wall' not in doc.layers: doc.layers.add('@wall')
    msp.add_lwpolyline([(0,0),(10000,0),(10000,10000),(0,10000)],close=True,dxfattribs={'layer':'@wall'}).translate(20000*s/100,20000*s/100,0)
    msp.add_text('고연리 1525 / 생산관리지역 / SMOKE MASS 10x10x7m (placeholder)',height=500*s/100,dxfattribs={'layer':'TEX1'}).set_placement((20000*s/100,17000*s/100))
doc.saveas(out); print('scale',ins.dxf.xscale,'layers',len(doc.layers),'dimstyles',len(doc.dimstyles),'blocks',len(doc.blocks))
