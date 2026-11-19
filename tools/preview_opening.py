#!/usr/bin/env python3
"""Render source-mesh authoring previews. These are NOT emulator captures.

Requires Pillow and NumPy. No ROM, downloaded model, or game texture is read.
"""
from __future__ import annotations
import argparse
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from character_models import human, pokemon
from pallet_town import Geometry
from kanto_layout import ORDER


def posed_human(kind=0):
    parts=human(kind)
    faces=[]
    def add(part,x,y,z,rx=0):
        for tri,color in parts[part].faces:
            transformed=[]
            for px,py,pz in tri:
                transformed.append((px+x,py*math.cos(rx)-pz*math.sin(rx)+y,
                                    py*math.sin(rx)+pz*math.cos(rx)+z))
            faces.append((tuple(transformed),color))
    add('Body',0,24,0);add('Head',0,42,0)
    for side in (-1,1):
        add('Thigh',side*5,24,0);add('Shin',side*5,13,0);add('Shoe',side*5,4,0)
        add('Arm',side*10,40,0);add('Forearm',side*10,32,0,-.18)
    return faces


def render(faces,size,yaw=0,pitch=22):
    image=Image.new('RGB',size,(226,231,222));draw=ImageDraw.Draw(image)
    yaw,pitch=math.radians(yaw),math.radians(pitch)
    projected=[]
    for tri,color in faces:
        pts=[]
        for x,y,z in tri:
            x,z=x*math.cos(yaw)-z*math.sin(yaw),x*math.sin(yaw)+z*math.cos(yaw)
            pts.append((x,y*math.cos(pitch)-z*math.sin(pitch),y*math.sin(pitch)+z*math.cos(pitch)))
        projected.append((pts,color))
    allpts=[p for pts,_ in projected for p in pts]
    lo=[min(p[i] for p in allpts) for i in (0,1)];hi=[max(p[i] for p in allpts) for i in (0,1)]
    scale=min((size[i]-24)/(hi[i]-lo[i]) for i in (0,1))
    cx,cy=(lo[0]+hi[0])/2,(lo[1]+hi[1])/2
    pixels=np.empty((size[1],size[0],3),dtype=np.uint8);pixels[:]=(226,231,222)
    depth=np.full((size[1],size[0]),-np.inf)
    for pts,color in projected:
        a,b,c=[(size[0]/2+(x-cx)*scale,size[1]/2-(y-cy)*scale,z) for x,y,z in pts]
        left=max(0,math.floor(min(a[0],b[0],c[0])));right=min(size[0]-1,math.ceil(max(a[0],b[0],c[0])))
        top=max(0,math.floor(min(a[1],b[1],c[1])));bottom=min(size[1]-1,math.ceil(max(a[1],b[1],c[1])))
        det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(det)<1e-7 or left>right or top>bottom: continue
        yy,xx=np.mgrid[top:bottom+1,left:right+1];xx=xx+.5;yy=yy+.5
        wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/det
        wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/det;wc=1-wa-wb
        zz=wa*a[2]+wb*b[2]+wc*c[2]
        dest=depth[top:bottom+1,left:right+1]
        visible=(wa>=-1e-8)&(wb>=-1e-8)&(wc>=-1e-8)&(zz>dest)
        dest[visible]=zz[visible]
        pixels[top:bottom+1,left:right+1][visible]=color
    return Image.fromarray(pixels)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('build/opening-previews'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    try: font=ImageFont.truetype('DejaVuSans.ttf',19)
    except OSError: font=ImageFont.load_default()
    sheet=Image.new('RGB',(1200,610),(26,42,49));draw=ImageDraw.Draw(sheet)
    draw.text((24,16),'Original Red mesh | 490 triangles | Source preview, not an emulator capture',font=font,fill='white')
    for i,(yaw,label) in enumerate(((0,'Front'),(-38,'Three-quarter'),(150,'Backpack'))):
        sheet.paste(render(posed_human(),(380,500),yaw,12),(10+i*400,63))
        draw.text((24+i*400,574),label,font=font,fill='white')
    sheet.save(args.output/'red-model.png')
    worlds=Image.new('RGB',(1500,1150),(26,42,49));draw=ImageDraw.Draw(worlds)
    draw.text((24,16),'Opening area geometry | Original map coordinates | Source preview, not an emulator capture',font=font,fill='white')
    panels=[(0,60,850,1050)]+[(870+(i%2)*315,60+(i//2)*545,300,480) for i in range(4)]
    for name,(x,y,w,h) in zip(ORDER,panels):
        worlds.paste(render(Geometry().make(name).faces,(w,h),0,68),(x,y))
        draw.text((x+12,y+h+8),name,font=font,fill='white')
    worlds.save(args.output/'opening-maps.png')
    starters=Image.new('RGB',(1200,420),(26,42,49));draw=ImageDraw.Draw(starters)
    for i,(species,label) in enumerate(((1,'Bulbasaur fallback'),(4,'Charmander'),(7,'Squirtle'),(19,'Rattata'))):
        starters.paste(render(pokemon(species).faces,(290,340),-25,18),(i*300,20))
        draw.text((i*300+12,380),label,font=font,fill='white')
    starters.save(args.output/'pokemon-models.png')
    print('Source authoring previews:',args.output)


if __name__=='__main__': main()
