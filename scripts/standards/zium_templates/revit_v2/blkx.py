import sys

import ezdxf
from ezdxf.addons import Importer

src = ezdxf.readfile(sys.argv[1]); out=sys.argv[2]
for e in src.modelspace().query('INSERT'):
    if e.dxf.layer in ('방위표','SYM','BUBL','TIT') or e.dxf.name in ('버블','arrowx'):
        print('INS', e.dxf.name, e.dxf.layer, round(e.dxf.xscale,3), [ (a.dxf.tag,a.dxf.text) for a in e.attribs][:3])
for name in sys.argv[3:]:
    d = ezdxf.new('R2018'); d.header['$INSUNITS']=4
    imp = Importer(src, d); imp.import_block(name); imp.finalize()
    blk = d.blocks.get(name)
    for ent in blk: d.modelspace().add_entity(ent.copy())
    safe = {'버블':'BUBBLE'}.get(name, name.replace('$','_'))
    d.saveas(f"{out}\\ZIUM_{safe}.dxf"); print('saved', name, '->', f"ZIUM_{safe}.dxf", [ (e.dxftype(), e.dxf.layer) for e in blk][:6])
