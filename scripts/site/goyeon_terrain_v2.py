import json
import math

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import uniform_filter
from shapely.geometry import Point, Polygon

E0,N0=395925,319220
to4326=Transformer.from_crs(5186,4326,always_xy=True)
ds=rasterio.open('dem.tif');A=ds.read(1).astype(float)
def dsm(x,y):
  lon,lat=to4326.transform(E0+x,N0+y); c,r=~ds.transform*(lon,lat); c-=.5;r-=.5;i,j=int(r),int(c);fr,fc=r-i,c-j
  return A[i,j]*(1-fr)*(1-fc)+A[i,j+1]*(1-fr)*fc+A[i+1,j]*fr*(1-fc)+A[i+1,j+1]*fr*fc
o=json.load(open('site_data.json'));base=o['base_dsm']
so=json.load(open('/workspace/su/site_outline.json')) if False else None
site=Polygon([(3.27,2.653),(3.392,5.075),(2.536,6.831),(0.661,9.492),(-0.258,12.658),(0.04,16.501),(1.854,18.61),(4.373,20.85),(4.453,24.361),(6.345,27.306),(6.945,31.097),(9.089,32.806),(12.936,36.708),(13.447,40.48),(18.901,41.465),(29.981,40.218),(40.264,40.508),(45.538,37.36),(55.525,33.833),(57.698,30.019),(59.644,27.467),(61.084,26.654),(61.763,22.707),(58.094,21.975),(54.614,17.657),(49.776,18.585),(47.388,22.571),(44.959,20.814),(41.139,20.429),(40.446,23.752),(38.338,21.786),(38.024,26.07),(36.054,31.199),(33.122,29.171),(31.122,23.126),(26.805,12.151),(23.328,13.804),(19.795,13.067),(14.492,3.128),(10.994,3.091),(10.209,0.118),(7.173,0.463),(6.588,1.703)])
LP=Polygon(o['lake'])
z,X0,Y0=18,225119,103430;im=np.asarray(Image.open('sat.jpg')).astype(float)
veg=((2*im[...,1]-im[...,0]-im[...,2]>18)&(im[...,1]>45)).astype(float); vegS=uniform_filter(veg,size=60)
def pix(x,y):
  lon,lat=to4326.transform(E0+x,N0+y);n=2**z
  return ((lon+180)/360*n-X0)*256, ((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n-Y0)*256
def vf(x,y):
  u,v=pix(x,y)
  return vegS[int(v),int(u)] if 0<=u<1536 and 0<=v<1536 else 0.8
CAN=6.0
step=5; xs=np.arange(-270,331,step); ys=np.arange(-280,321,step)
dtm=np.array([[dsm(x,y)-base-CAN*vf(x,y) for x in xs] for y in ys])
padv=np.mean([dtm[int(round((y-ys[0])/step)),int(round((x-xs[0])/step))] for x in range(5,60,5) for y in range(5,40,5) if site.contains(Point(x,y))])
dtm-=padv  # re-zero so canopy-corrected pad mean = 0
P=[];Z=[]
for j,y in enumerate(ys):
 for i,x in enumerate(xs):
  pt=Point(x,y); dd=site.distance(pt)
  if 20<dd<70 and not LP.buffer(10).contains(pt): P.append((x,y));Z.append(dtm[j,i])
Am=np.c_[np.array(P),np.ones(len(P))];c,*_=np.linalg.lstsq(Am,np.array(Z),rcond=None);rms=float(np.sqrt(np.mean((Am@c-Z)**2)))
cut=[];fill=[]
for x in np.arange(-1,62.5,0.5):
 for y in np.arange(0,42,0.5):
  if site.contains(Point(x,y)):
   zz=c[0]*x+c[1]*y+c[2]; (cut if zz>0 else fill).append(zz)
a=0.25
stats={'pad_offset_applied':round(float(padv),2),'plane':[round(float(v),4) for v in c],'rms':round(rms,2),'cut_area_m2':len(cut)*a,'fill_area_m2':len(fill)*a,'max_cut_m':round(max(cut),2) if cut else 0,'mean_cut_m':round(float(np.mean(cut)),2) if cut else 0,'cut_vol_m3':round(sum(cut)*a),'fill_vol_m3':round(-sum(fill)*a),'max_fill_m':round(-min(fill),2) if fill else 0}
corners={str(p):round(c[0]*p[0]+c[1]*p[1]+c[2],2) for p in [(18.9,41.5),(40.3,40.5),(0,12.7),(61.8,22.7),(10.2,0.1),(30,20)]}
print(stats,corners)
S=1/1.5; grid=np.zeros_like(dtm)
for j,y in enumerate(ys):
 for i,x in enumerate(xs):
  pt=Point(x,y); d=0 if site.contains(pt) else site.exterior.distance(pt)
  grid[j,i]=min(max(dtm[j,i],-S*d),S*d)
lakez=round(float(min(dtm[j,i] for j,y in enumerate(ys) for i,x in enumerate(xs) if LP.contains(Point(x,y)))),2)
o2=dict(o); o2.update({'step':step,'x0':int(xs[0]),'y0':int(ys[0]),'nx':len(xs),'ny':len(ys),'grid':np.round(grid,2).tolist(),'lake_z':lakez,'canopy_m':CAN,'cut':stats,'corners_natural':corners})
R,G,B=im[...,0],im[...,1],im[...,2];out=[]
for x,y,_,h in o['trees']:
  u,v=pix(x,y);u,v=int(u),int(v); r,g,b=[float(ch[v-3:v+4,u-3:u+4].mean()) for ch in (R,G,B)]
  conifer=(g<95 and (r+b)/2<g*0.80)
  jj=int(round((y-ys[0])/step)); ii=int(round((x-xs[0])/step))
  out.append([x,y,round(float(grid[jj,ii]),2),h,'pine' if conifer else 'decid'])
o2['trees']=out
print('lake z',lakez,'pine',sum(t[4]=='pine' for t in out),'decid',sum(t[4]=='decid' for t in out))
json.dump(o2,open('site_data_v2.json','w'))
