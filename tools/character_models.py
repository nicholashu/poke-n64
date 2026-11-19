"""Original low-poly characters and starter proxies, generated as N64 meshes.

No downloaded mesh, texture or ROM data is used. Positions are authored in
world units and stored at 100x precision; the native draw routine scales back.
"""
from __future__ import annotations
import math

SKIN=(220,171,123); WHITE=(242,238,214); INK=(37,40,45)
RED=(200,49,47); BLUE=(51,91,151); HAIR=(54,43,38)
HUMANS=("Red","Blue","Oak","Mom","Daisy","Girl","Scientist","Fisher")
PALETTES=((RED,BLUE,HAIR),( (91,78,137),(57,65,88),(115,76,39)),
          (WHITE,(111,81,61),(179,181,166)),((189,83,117),(134,66,91),HAIR),
          ((221,169,91),(188,133,66),(134,83,41)),((185,84,143),(101,65,123),(89,56,44)),
          (WHITE,(62,83,95),(82,58,41)),((90,134,147),(65,86,101),(75,57,46)))

class Mesh:
    def __init__(self): self.faces=[]
    def tri(self,a,b,c,color):
        ab=[b[i]-a[i] for i in range(3)]; ac=[c[i]-a[i] for i in range(3)]
        n=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
        length=math.sqrt(sum(v*v for v in n))
        if length<1e-7: raise ValueError("Degenerate character face")
        light=.78+.22*max(0,(n[0]*-.3+n[1]*.65+n[2]*.7)/length)
        shade=tuple(round(v*min(1,light)) for v in color)
        self.faces.append(((a,b,c),shade))
    def quad(self,a,b,c,d,color): self.tri(a,b,c,color); self.tri(a,c,d,color)
    def box(self,x,y,z,hx,hy,hz,color):
        x1,x2=x-hx,x+hx; y1,y2=y-hy,y+hy; z1,z2=z-hz,z+hz
        for q in (((x1,y1,z2),(x2,y1,z2),(x2,y2,z2),(x1,y2,z2)),
                  ((x2,y1,z1),(x1,y1,z1),(x1,y2,z1),(x2,y2,z1)),
                  ((x1,y1,z1),(x1,y1,z2),(x1,y2,z2),(x1,y2,z1)),
                  ((x2,y1,z2),(x2,y1,z1),(x2,y2,z1),(x2,y2,z2)),
                  ((x1,y2,z1),(x1,y2,z2),(x2,y2,z2),(x2,y2,z1)),
                  ((x2,y1,z1),(x2,y1,z2),(x1,y1,z2),(x1,y1,z1))): self.quad(*q,color)
    def taper(self,y1,y2,rx1,rz1,rx2,rz2,color,sides=6,x=0,z=0):
        rings=[]
        for y,rx,rz in ((y1,rx1,rz1),(y2,rx2,rz2)):
            rings.append([(x+rx*math.cos(2*math.pi*i/sides+math.pi/4),y,
                           z+rz*math.sin(2*math.pi*i/sides+math.pi/4)) for i in range(sides)])
        for i in range(sides):
            j=(i+1)%sides
            self.quad(rings[0][i],rings[0][j],rings[1][j],rings[1][i],color)
        for ring,flip in ((rings[0],True),(rings[1],False)):
            for i in range(1,sides-1):
                a,b,c=ring[0],ring[i],ring[i+1]
                self.tri(c,b,a,color) if flip else self.tri(a,b,c,color)
    def ellipsoid(self,x,y,z,rx,ry,rz,color,sides=8):
        rings=[]
        for latitude in (-math.pi/3,0,math.pi/3):
            rings.append([(x+rx*math.cos(latitude)*math.cos(i*2*math.pi/sides),
                           y+ry*math.sin(latitude),z+rz*math.cos(latitude)*math.sin(i*2*math.pi/sides)) for i in range(sides)])
        for a,b in zip(rings,rings[1:]):
            for i in range(sides): self.quad(a[i],a[(i+1)%sides],b[(i+1)%sides],b[i],color)
        for i in range(sides):
            self.tri((x,y-ry,z),rings[0][(i+1)%sides],rings[0][i],color)
            self.tri((x,y+ry,z),rings[-1][i],rings[-1][(i+1)%sides],color)


def human(kind):
    coat,pants,hair=PALETTES[kind]
    p={n:Mesh() for n in ('Body','Head','Arm','Forearm','Thigh','Shin','Shoe')}
    m=p['Body'];m.taper(0,17,7,4,9,5,coat,sides=4)
    m.box(0,-1,0,7,2,4,pants)
    # Undershirt, open vest edges, collar and backpack are separate silhouettes.
    m.quad((-3,1,4.6),(3,1,4.6),(3,15,5.1),(-3,15,5.1),INK if kind<2 else WHITE)
    m.tri((-8,16,5.2),(-2,13,5.2),(-2,18,2),WHITE)
    m.tri((8,16,5.2),(2,18,2),(2,13,5.2),WHITE)
    if kind==0:
        m.box(0,8,-6,6,8,3,(154,105,57))
        m.box(0,6,-9.2,4.4,4.5,.4,(187,134,72))
        for x in (-5.5,5.5): m.box(x,10,5.5,.8,7,.5,(153,110,63))
    if kind in (3,4,5): m.taper(-5,7,10,5,7,4,coat,sides=6)
    m=p['Head'];m.taper(0,10,6,5.5,7.6,6.8,SKIN,sides=8)
    m.taper(10,14,7.6,6.8,5.3,5.2,hair,sides=8)
    for side in (-1,1):
        m.box(side*7.5,6,0,1.3,2,1.7,SKIN)
        m.box(side*6.7,10,2,.8,3,2.3,hair)
        x=side*2.9
        m.quad((x-1.6,5.4,6.6),(x+1.6,5.4,6.6),(x+1.6,8.7,6.6),(x-1.6,8.7,6.6),WHITE)
        m.quad((x-.6,5.5,6.8),(x+.6,5.5,6.8),(x+.6,8.1,6.8),(x-.6,8.1,6.8),INK)
        m.box(x,9.2,6.4,1.7,.45,.4,hair)
    m.tri((-.9,4.8,6.6),(.9,4.8,6.6),(0,6.5,8.5),(204,151,106))
    m.quad((-1.8,2.4,6.3),(1.8,2.4,6.3),(1.8,2.8,6.3),(-1.8,2.8,6.3),(117,77,64))
    if kind==0:
        m.taper(11.8,17,8.8,8,7,6,RED,sides=8)
        m.box(0,12,9,7,.8,4.2,RED)
        m.quad((-4.5,12.5,8.2),(4.5,12.5,8.2),(3.8,16.5,6.5),(-3.8,16.5,6.5),WHITE)
        m.tri((-1,13.2,8.0),(1.5,13.2,8.0),(.5,15.4,7.2),(75,128,76))
    elif kind==1:
        for x in (-5,0,5):
            m.tri((x-3,12,-3),(x+3,12,-3),(x+1,19,-1),hair)
    elif kind in (3,4,5): m.box(0,6,-5.8,6.2,7,2.5,hair)
    elif kind==7: m.taper(12,16,8,7,7,6,(180,171,125),sides=6)
    m=p['Arm'];m.taper(-8,0,3.8,3.8,4.7,4.2,WHITE if kind<2 else coat,sides=6)
    m=p['Forearm'];m.taper(-8,0,2.6,2.7,3.2,3.2,SKIN,sides=6);m.box(0,-9,0,2.7,2.4,2.8,SKIN)
    m=p['Thigh'];m.taper(-11,0,3.6,3.7,4.3,4.1,pants,sides=6)
    m=p['Shin'];m.taper(-9,0,2.9,3.2,3.5,3.6,pants,sides=6)
    m=p['Shoe'];m.box(0,-1,2.2,3.7,2.8,6,WHITE);m.box(0,1.1,1.8,3.3,1.6,4.9,RED if kind==0 else INK)
    return p


def pokemon(species):
    m=Mesh()
    if species==1:
        m.ellipsoid(0,12,0,13,10,16,(87,166,146),6)
        m.ellipsoid(0,18,14,14,12,11,(108,188,163),6)
        m.taper(17,34,13,12,3,3,(67,122,76),6,z=-4)
        for x in (-9,9):
            for z in (-9,8): m.box(x,5,z,4.5,5,5,(83,155,139))
        for x in (-6,6):
            m.box(x,20,24,.9,2.8,.7,(165,49,61))
            m.tri((x-3,26,14),(x+3,26,14),(x,35,13),(83,154,139))
    elif species==4:
        m.ellipsoid(0,16,0,10,15,10,(219,128,66),6)
        m.ellipsoid(0,37,4,11,12,10,(232,146,74),6)
        m.box(0,15,9,6,10,1.8,(244,210,140))
        for x in (-8,8): m.box(x,4,4,4,4,7,(218,123,62))
        for x in (-11,11): m.box(x,21,2,3,6,3,(218,123,62))
        m.box(0,9,-14,3,3,9,(219,128,66))
        m.taper(9,26,5,5,.5,.5,(237,77,44),6,z=-22)
        m.taper(9,19,3,3,.5,.5,(255,205,73),6,z=-23)
        for x in (-5,5): m.box(x,40,12,1.2,3,.8,INK)
    elif species==19:
        purple=(146,102,163)
        m.ellipsoid(0,11,-2,11,9,15,purple,6)
        m.ellipsoid(0,20,12,12,10,11,purple,6)
        for x in (-8,8):
            m.ellipsoid(x,30,9,5,7,2,purple,6)
            m.box(x,3,7,4,3,7,(224,191,166))
            m.box(x*.55,22,22,1.3,2,.7,INK)
        m.box(0,15,23,5,3,3,(230,207,178))
        m.box(0,9,-21,2,2,9,(193,151,156))
    else:
        m.ellipsoid(0,18,0,13,15,12,(142,102,59),8)
        m.ellipsoid(0,18,7,10,12,7,(224,202,142),6)
        m.ellipsoid(0,39,5,11,11,10,(104,177,195),8)
        for x in (-10,10):
            m.box(x,4,4,4,4,7,(104,177,195))
            m.box(x*1.2,22,6,3.4,6,3.4,(104,177,195))
        m.ellipsoid(0,7,-15,4,5,6,(104,177,195),6)
        for x in (-5,5): m.box(x,41,14,1.2,2.8,.8,(104,53,65))
        # Simple raised shell seams.
        m.box(0,21,-12,.6,9,.6,(93,66,44))
    return m


def emit_mesh(name,mesh):
    lines=[]
    groups=[mesh.faces[i:i+10] for i in range(0,len(mesh.faces),10)]
    for i,group in enumerate(groups):
        lines.append(f'static Vtx {name}V{i}[] __attribute__((aligned(16))) = {{')
        for tri,color in group:
            for p in tri:
                coords=[round(v*100) for v in p]
                if any(abs(v)>32767 for v in coords): raise ValueError('Character vertex exceeds s16')
                lines.append('    { .v = { .ob = { '+', '.join(map(str,coords))+' }, .flag = 0, .tc = {0,0}, .cn = { '+', '.join(map(str,color))+',255 } } },')
        lines.append('};')
    lines.append(f'static Gfx {name}[] = {{')
    for i,group in enumerate(groups):
        lines.append(f'    gsSPVertex({name}V{i}, {len(group)*3}, 0),')
        for j in range(0,len(group),2):
            a=j*3
            if j+1<len(group): lines.append(f'    gsSP2Triangles({a},{a+1},{a+2},0,{a+3},{a+4},{a+5},0),')
            else: lines.append(f'    gsSP1Triangle({a},{a+1},{a+2},0),')
    lines += ['    gsSPEndDisplayList(),','};']
    return '\n'.join(lines)


def source():
    lines=['/* Generated original character geometry. No imported asset data. */',
           '#include "poke_red.h"','#include "sys_matrix.h"','#include "sys_math.h"','#include "gfx.h"','#include "z_lib.h"']
    for i,name in enumerate(HUMANS):
        for part,mesh in human(i).items(): lines.append(emit_mesh('s'+name+part,mesh))
    for species in (1,4,7,19): lines.append(emit_mesh('sMon'+str(species),pokemon(species)))
    lines.append('static Gfx* sHumans[8][7] = {')
    for name in HUMANS: lines.append('    { '+', '.join('s'+name+p for p in human(0))+' },')
    lines+=['};',r'''
static void draw_part(GraphicsContext* gfx,Gfx* part,f32 x,f32 y,f32 z,f32 rx) {
    Matrix_Push();
    Matrix_Translate(x*100.0f,y*100.0f,z*100.0f,MTXMODE_APPLY);
    Matrix_RotateX(rx,MTXMODE_APPLY);
    OPEN_DISPS(gfx);
    MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++,gfx);
    gSPDisplayList(POLY_OPA_DISP++,part);
    CLOSE_DISPS(gfx);
    Matrix_Pop();
}
void PokeModels_DrawHuman(GraphicsContext* gfx,s32 kind,f32 phase,f32 amount) {
    Gfx** p;
    s32 side;
    f32 swing;
    if (kind<0 || kind>=8) return;
    p=sHumans[kind];
    Matrix_Push();
    Matrix_Scale(.01f,.01f,.01f,MTXMODE_APPLY);
    draw_part(gfx,p[0],0,24,0,0);
    draw_part(gfx,p[1],0,42,0,0);
    for (side=-1;side<=1;side+=2) {
        swing=Math_SinF(phase)*amount*side;
        Matrix_Push();
        Matrix_Translate(side*5.0f*100,24*100,0,MTXMODE_APPLY);
        Matrix_RotateX(swing*.58f,MTXMODE_APPLY);
        draw_part(gfx,p[4],0,0,0,0);
        Matrix_Translate(0,-11*100,0,MTXMODE_APPLY);
        Matrix_RotateX(swing<0 ? -swing*.65f : 0,MTXMODE_APPLY);
        draw_part(gfx,p[5],0,0,0,0);
        draw_part(gfx,p[6],0,-9,0,0);
        Matrix_Pop();
        Matrix_Push();
        Matrix_Translate(side*10.0f*100,40*100,0,MTXMODE_APPLY);
        Matrix_RotateX(-swing*.65f,MTXMODE_APPLY);
        draw_part(gfx,p[2],0,0,0,0);
        draw_part(gfx,p[3],0,-8,0,-.18f);
        Matrix_Pop();
    }
    Matrix_Pop();
}
void PokeModels_DrawPokemon(GraphicsContext* gfx,s32 species) {
    Gfx* mesh=species==1 ? sMon1 : species==4 ? sMon4 : species==19 ? sMon19 : sMon7;
    Matrix_Push();
    Matrix_Scale(.01f,.01f,.01f,MTXMODE_APPLY);
    OPEN_DISPS(gfx);
    MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++,gfx);
    gSPDisplayList(POLY_OPA_DISP++,mesh);
    CLOSE_DISPS(gfx);
    Matrix_Pop();
}
''']
    return '\n'.join(lines)


def statistics():
    return {'humans':{name:sum(len(m.faces)*(1 if part in ('Body','Head') else 2) for part,m in human(i).items()) for i,name in enumerate(HUMANS)},
            'starters':{s:len(pokemon(s).faces) for s in (1,4,7,19)}}


if __name__=='__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(source())
    print(statistics())
