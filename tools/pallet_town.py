#!/usr/bin/env python3
"""Build an original Pallet Town OoT scene and room with native collision.

The experimental total conversion uses the SCENE_KOKIRI_FOREST scene slot as a
temporary staging slot, replacing *its ROM scene/room payloads* with original
Pallet Town geometry. No Kokiri mesh, rooms, NPCs or scene collision are loaded.

All 3D vertices are authored here. Exact semantic map coordinates and
passability come from the pinned original map reference in kanto_layout.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import chain
from kanto_layout import CELL, ORDER, ROOMS, bounds as map_bounds, point, walkable

Vec = tuple[int, int, int]
Color = tuple[int, int, int]

GRASS = (105, 162, 99)
GRASS_DARK = (82, 144, 78)
ROAD = (205, 186, 140)
ROAD_EDGE = (173, 157, 115)
WHITE = (244, 230, 197)
CREAM = (235, 214, 164)
RED = (190, 77, 70)
ROOF_BLUE = (84, 124, 178)
LAB_ROOF = (104, 94, 157)
TRUNK = (116, 93, 68)
LEAVES = (67, 128, 63)
LEAVES_LIGHT = (91, 165, 76)
SEA = (88, 145, 174)
WINDOW = (117, 181, 211)


@dataclass(frozen=True)
class Landmark:
    name: str
    x: int
    z: int
    half_w: int
    half_d: int
    height: int
    roof: Color
    wall: Color


def _landmark(b):
    x,z=point("PalletTown", b["x"]+(b["width"]-1)/2, b["y"]+(b["height"]-1)/2)
    names={"reds_house":"Red's house","blues_house":"Rival's house","oaks_lab":"Professor Oak's laboratory"}
    return Landmark(names[b["name"]],x,z,b["width"]*CELL//2,b["height"]*CELL//2,
                    138 if b["name"]=="oaks_lab" else 116,RED,CREAM)

LANDMARKS=tuple(_landmark(b) for b in ROOMS["PalletTown"]["buildings"])
TREES=()  # Original perimeter uses rounded obstacles, not invented tall trees.
SPAWN=(*point("PalletTown",5,6),)
SPAWN=(SPAWN[0],0,SPAWN[1])
WORLD_BOUNDS=map_bounds("PalletTown")


def _normal(a: Vec, b: Vec, c: Vec) -> tuple[float, float, float]:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (ab[1]*ac[2] - ab[2]*ac[1],
             ab[2]*ac[0] - ab[0]*ac[2],
             ab[0]*ac[1] - ab[1]*ac[0])
    norm = math.sqrt(sum(v*v for v in cross))
    if norm == 0:
        raise ValueError("Degenerate native Pallet collision face")
    return tuple(v / norm for v in cross)


class Geometry:
    def __init__(self):
        self.faces: list[tuple[tuple[Vec, Vec, Vec], Color]] = []
        self.coll_faces: list[tuple[Vec, Vec, Vec]] = []

    def tri(self, a: Vec, b: Vec, c: Vec, color: Color):
        self.faces.append(((a, b, c), color))

    def quad(self, a: Vec, b: Vec, c: Vec, d: Vec, color: Color):
        self.tri(a, b, c, color)
        self.tri(a, c, d, color)

    def collision_quad(self, a: Vec, b: Vec, c: Vec, d: Vec):
        # No material flags, all scene collision uses normal OoT surfaces.
        self.coll_faces.extend(((a, b, c), (a, c, d)))

    def flat(self, x1: int, z1: int, x2: int, z2: int, y: int, color: Color):
        self.quad((x1,y,z1), (x1,y,z2), (x2,y,z2), (x2,y,z1), color)

    def box(self, x: int, z: int, hx: int, hz: int, height: int,
            color: Color, collide=False, y0=0):
        x1,x2 = x-hx,x+hx
        z1,z2 = z-hz,z+hz
        y1,y2 = y0,y0+height
        sides = [
            ((x1,y1,z2),(x2,y1,z2),(x2,y2,z2),(x1,y2,z2)),
            ((x2,y1,z1),(x1,y1,z1),(x1,y2,z1),(x2,y2,z1)),
            ((x1,y1,z1),(x1,y1,z2),(x1,y2,z2),(x1,y2,z1)),
            ((x2,y1,z2),(x2,y1,z1),(x2,y2,z1),(x2,y2,z2)),
        ]
        for face in sides:
            self.quad(*face, color)
            if collide:
                self.collision_quad(*face)
        self.quad((x1,y2,z1),(x1,y2,z2),(x2,y2,z2),(x2,y2,z1), color)

    def tree(self, x: int, z: int):
        self.box(x,z,19,19,145,TRUNK,collide=True)
        self.box(x,z,64,64,80,LEAVES,y0=115)
        self.box(x,z,51,51,85,LEAVES_LIGHT,y0=181)
        self.box(x,z,35,35,52,LEAVES,y0=248)

    def prism(self, x, z, rx, rz, y, height, color, sides=8):
        ring=[(round(x+rx*math.cos(i*2*math.pi/sides)),y,
               round(z+rz*math.sin(i*2*math.pi/sides))) for i in range(sides)]
        for i,a in enumerate(ring):
            b=ring[(i+1)%sides]
            shade=tuple(round(c*(0.80+0.20*(i%3)/2)) for c in color)
            self.quad(a,b,(b[0],y+height,b[2]),(a[0],y+height,a[2]),shade)
            self.tri((x,y+height,z),(a[0],y+height,a[2]),(b[0],y+height,b[2]),color)

    def building(self, b: Landmark, data):
        x1,x2=b.x-b.half_w,b.x+b.half_w
        z1,z2=b.z-b.half_d,b.z+b.half_d
        h=b.height
        door_x,_=point("PalletTown",*data["door"])
        dx1,dx2=door_x-CELL//2,door_x+CELL//2
        # No wall across the passable door cell. Its alcove reaches the warp.
        for left,right in ((x1,dx1),(dx2,x2)):
            self.quad((left,0,z2),(right,0,z2),(right,h,z2),(left,h,z2),b.wall)
        self.quad((x1,0,z1),(x1,h,z1),(x2,h,z1),(x2,0,z1),b.wall)
        self.quad((x1,0,z1),(x1,0,z2),(x1,h,z2),(x1,h,z1),WHITE)
        self.quad((x2,0,z2),(x2,0,z1),(x2,h,z1),(x2,h,z2),CREAM)
        self.quad((dx1,0,z2-CELL+1),(dx2,0,z2-CELL+1),
                  (dx2,84,z2-CELL+1),(dx1,84,z2-CELL+1),TRUNK)
        self.quad((dx1,84,z2),(dx2,84,z2),(dx2,h,z2),(dx1,h,z2),b.wall)
        # Dark door opening remains readable at the outdoor follow-camera angle.
        # It is visual only; entering this passable cell starts the native warp.
        self.quad((dx1+7,0,z2+1),(dx2-7,0,z2+1),
                  (dx2-7,80,z2+1),(dx1+7,80,z2+1),(48,60,49))
        peak=h+52
        self.quad((x1,h,z1),(x1,peak,b.z),(x2,peak,b.z),(x2,h,z1),b.roof)
        self.quad((x1,peak,b.z),(x1,h,z2),(x2,h,z2),(x2,peak,b.z),tuple(int(c*.82) for c in b.roof))
        self.tri((x1,h,z1),(x1,h,z2),(x1,peak,b.z),CREAM)
        self.tri((x2,h,z2),(x2,h,z1),(x2,peak,b.z),CREAM)
        # Original window rhythm and horizontal facade trim, authored in 3D.
        for cx in range(data["x"],data["x"]+data["width"]):
            wx,_=point("PalletTown",cx,data["y"])
            if cx==data["door"][0]: continue
            self.quad((wx-24,42,z2+1),(wx+24,42,z2+1),(wx+24,80,z2+1),(wx-24,80,z2+1),WINDOW)
            self.box(wx,z2+2,2,1,38,WHITE,y0=42)
        self.box(b.x,z2+2,b.half_w,2,7,WHITE,y0=89)
        for offset in (-36,0,36):
            # Roof strips do not extend the original footprint.
            z=b.z+offset
            y=peak-round(abs(offset)*52/b.half_d)+1
            self.flat(x1,z,x2,z+2,y,tuple(min(255,c+18) for c in b.roof))

    def outdoors(self):
        room=ROOMS["PalletTown"]
        x1,z1,x2,z2=self.bounds
        self.flat(x1,z1,x2,z2,-2,(145,180,113))
        # Preserve original 8px ground-pattern positions, with original 3D detail.
        for rz,row in enumerate(room["ground_rows"]):
            for rx,kind in enumerate(row):
                if kind not in "gdf": continue
                x=x1+rx*CELL//2; z=z1+rz*CELL//2
                if kind in "df": self.flat(x,z,x+CELL//2,z+CELL//2,-1,GRASS)
                for ox,oz in ((8,12),(21,24)) if kind=="g" else ((7,8),(23,24)):
                    self.tri((x+ox,0,z+oz),(x+ox+3,6,z+oz),(x+ox+7,0,z+oz+2),GRASS_DARK)
        for b,data in zip(LANDMARKS,room["buildings"]): self.building(b,data)
        for z,row in enumerate(room["semantic_rows"]):
            for x,kind in enumerate(row):
                wx,wz=point("PalletTown",x,z)
                if kind=="B":
                    self.prism(wx,wz,35,35,0,53,(105,130,106))
                    self.prism(wx,wz,29,29,53,18,(161,182,145))
                elif kind=="F":
                    for delta in (-23,23): self.box(wx+delta,wz,6,8,42,WHITE)
                    self.box(wx,wz,38,5,8,TRUNK,y0=24)
                elif kind=="S":
                    self.box(wx,wz,6,6,38,TRUNK)
                    self.box(wx,wz,31,5,29,WHITE,y0=28)
                    for y in (35,43,51): self.box(wx,wz+6,23,1,2,TRUNK,y0=y)
                elif kind=="~":
                    self.flat(wx-40,wz-40,wx+40,wz+40,-1,SEA)
                    for offset in (-21,12): self.flat(wx-26,wz+offset,wx+26,wz+offset+3,0,(160,207,216))
                elif kind=="T":
                    self.flat(wx-40,wz-40,wx+40,wz+40,-1,GRASS_DARK)
                    for dx in (-24,0,24):
                        for dz in (-23,4,25):
                            self.tri((wx+dx-9,0,wz+dz),(wx+dx,24,wz+dz),(wx+dx+8,0,wz+dz+2),LEAVES)
        for f in room["flowers"]:
            # Reference values identify centers in cell-edge coordinates.
            x,z=point("PalletTown",f["x"]-.5,f["y"]-.5)
            self.box(x,z,2,2,14,LEAVES)
            for dx,dz in ((-7,0),(7,0),(0,-7),(0,7)):
                self.flat(x+dx-5,z+dz-5,x+dx+5,z+dz+5,14,(238,222,174))
            self.flat(x-4,z-4,x+4,z+4,15,(220,161,65))

    def interiors(self):
        room=ROOMS[self.room_name]
        x1,z1,x2,z2=self.bounds
        lab=self.room_name=="OaksLab"
        self.flat(x1,z1,x2,z2,-1,(204,197,163) if lab else (191,150,104))
        # Cutaway walls keep all original floor cells visible from the native camera.
        self.box(0,z1+8,(x2-x1)//2,8,136,(218,223,203))
        self.box(x1+4,0,4,(z2-z1)//2,36,CREAM)
        self.box(x2-4,0,4,(z2-z1)//2,36,CREAM)
        for z in range(room["dimensions"][1]):
            for x in range(room["dimensions"][0]):
                wx,wz=point(self.room_name,x,z)
                if lab:
                    if (x+z)%2==0: self.flat(wx-39,wz-39,wx+39,wz+39,0,(186,193,167))
                else:
                    self.flat(wx-39,wz+36,wx+39,wz+38,0,(166,124,83))
        for feature in room.get("features",[]):
            kind=feature["kind"]
            if "bounds" in feature: x,z,w,d=feature["bounds"]
            else: x,z=feature["at"]; w=d=1
            wx,wz=point(self.room_name,x+(w-1)/2,z+(d-1)/2)
            hw,hd=w*CELL//2-5,d*CELL//2-5
            if kind=="window":
                self.quad((wx-25,55,z1+18),(wx+25,55,z1+18),(wx+25,108,z1+18),(wx-25,108,z1+18),WINDOW)
                self.box(wx,z1+19,2,1,53,WHITE,y0=55)
            elif kind in ("poster","wall_map"):
                self.quad((wx-27,56,z1+18),(wx+27,56,z1+18),(wx+27,111,z1+18),(wx-27,111,z1+18),WHITE)
                self.quad((wx-17,65,z1+19),(wx+17,65,z1+19),(wx+17,100,z1+19),(wx-17,100,z1+19),GRASS)
            elif kind=="bed":
                self.box(wx,wz,hw,hd,18,TRUNK)
                self.box(wx,wz,hw-2,hd-3,10,RED,y0=18)
                self.box(wx,wz-hd+18,hw-5,14,7,WHITE,y0=28)
            elif kind=="plant":
                self.prism(wx,wz+12,20,20,0,26,(155,99,68),6)
                self.prism(wx,wz+12,29,29,26,37,LEAVES,6)
            elif kind=="bookshelves":
                self.box(wx,wz,hw,hd,90,TRUNK)
                for shelf in (19,44,69):
                    self.box(wx,wz+hd+1,hw-5,2,3,CREAM,y0=shelf)
                    for bx in range(wx-hw+8,wx+hw-7,12):
                        self.box(bx,wz+hd+3,4,2,16,(91+(bx%3)*32,114,147),y0=shelf+3)
            elif kind=="chair":
                # Visual chair only: original chairs are passable.
                self.box(wx,wz,17,17,4,TRUNK,y0=20)
                self.box(wx,wz-17,17,3,24,TRUNK,y0=20)
            elif kind in ("pc","computer_workbench","tv"):
                self.box(wx,wz,hw,hd,30,TRUNK)
                self.box(wx,wz,hw-9,min(hd,18),35,(62,69,67),y0=30)
                self.quad((wx-hw+14,37,wz+19),(wx+hw-14,37,wz+19),(wx+hw-14,58,wz+19),(wx-hw+14,58,wz+19),WINDOW)
            elif kind=="console":
                self.box(wx,wz,25,18,12,(184,188,186))
                self.box(wx,wz+5,18,8,3,(71,66,82),y0=12)
            else:
                self.box(wx,wz,hw,hd,7,(206,174,122),y0=40)
                for dx in (-hw+7,hw-7):
                    for dz in (-hd+7,hd-7): self.box(wx+dx,wz+dz,5,5,40,TRUNK)
                if kind=="pokedex_table":
                    for dx in (-CELL//2,CELL//2): self.box(wx+dx,wz,15,20,4,RED,y0=47)
        if self.room_name=="BluesHouse":
            # The map is visible on Daisy's table; receiving it is a later quest.
            wx,wz=point(self.room_name,3,3)
            self.flat(wx-22,wz-26,wx+22,wz+26,48,WHITE)
            self.flat(wx-15,wz-19,wx+15,wz+19,49,GRASS)
            self.flat(wx-3,wz-19,wx+3,wz+19,50,ROAD)
        for warp in room["warps"]:
            wx,wz=point(self.room_name,*warp["at"])
            if warp.get("kind","").startswith("stairs"):
                for i in range(5): self.box(wx,wz-28+i*13,34,5,3+i*4,(225,217,184))
            else: self.flat(wx-39,wz-39,wx+39,wz+39,1,(175,72,64))

    def map_collision(self):
        room=ROOMS[self.room_name]
        width,height=room["dimensions"]
        x0,z0,_,_=self.bounds
        # Independent floor quads and edge walls preserve every passability cell.
        # No collision on chair/flower cells; water has no walkable floor.
        self.blocking_edges=[]
        for z in range(height):
            for x in range(width):
                if not walkable(self.room_name,x,z): continue
                x1,z1=x0+x*CELL,z0+z*CELL; x2,z2=x1+CELL,z1+CELL
                self.collision_quad((x1,0,z1),(x1,0,z2),(x2,0,z2),(x2,0,z1))
                for dx,dz,a,b in ((-1,0,(x1,0,z2),(x1,0,z1)),
                                   (1,0,(x2,0,z1),(x2,0,z2)),
                                   (0,-1,(x1,0,z1),(x2,0,z1)),
                                   (0,1,(x2,0,z2),(x1,0,z2))):
                    if walkable(self.room_name,x+dx,z+dz): continue
                    self.blocking_edges.append((x,z,dx,dz))
                    # Wind toward the walkable cell. Walls prevent jumping
                    # across Game Boy obstacles that have no passable top.
                    self.collision_quad(a,b,(b[0],240,b[2]),(a[0],240,a[2]))

    def make(self, room_name="PalletTown"):
        self.room_name=room_name
        self.bounds=map_bounds(room_name)
        if room_name=="PalletTown": self.outdoors()
        else: self.interiors()
        self.map_collision()
        return self


def _collision_data(geom: Geometry):
    vertices: list[Vec] = []
    lookup: dict[Vec,int] = {}
    polys = []
    for tri in geom.coll_faces:
        indices = []
        for point in tri:
            if point not in lookup:
                lookup[point] = len(vertices)
                vertices.append(point)
            indices.append(lookup[point])
        normal = _normal(*tri)
        packed_normal = tuple(int(round(max(-1.0,min(1.0,n))*32767)) for n in normal)
        dist = round(-sum(normal[i]*tri[0][i] for i in range(3)))
        if abs(dist)>32767:
            raise ValueError("Native Pallet collision plane is outside s16 range")
        polys.append((indices, packed_normal, dist))
    if len(vertices)>8191:
        raise ValueError("Native Pallet collision exceeds OoT vertex index limit")
    return vertices, polys


def scene_source(geom: Geometry, *, bounds=None, spawn=None, spawn_list=None) -> str:
    """Emit a scene with explicit bounds/spawn for generated maps as well.

    Defaults preserve every opening room and its entrance list. ROM importers
    supply their own bounds and outdoor spawn without changing module globals.
    """
    vertices, polys = _collision_data(geom)
    room_name=getattr(geom,"room_name","PalletTown")
    x1,z1,x2,z2=bounds if bounds is not None else geom.bounds
    if spawn_list is not None:
        if spawn is not None:
            raise ValueError("Use either one preview spawn or the full opening spawn list")
        spawns=list(spawn_list)
        if not 1<=len(spawns)<=8 or any(len(entry)!=4 for entry in spawns):
            raise ValueError("Native scene requires 1..8 (x,y,z,yaw) spawn entries")
    elif spawn is None:
        spawns=[(*point(room_name,x,z),yaw) for x,z,yaw in ROOMS[room_name]["spawns"]]
        spawns=[(x,0,z,yaw) for x,z,yaw in spawns]
    else:
        spawns=[(*spawn,180)]
    lines = [
        '/* Original Pallet Town scene, replacing the Kokiri staging scene slot. */',
        '#include "ultra64.h"',
        '#include "scene.h"',
        '#include "room.h"',
        '#include "player.h"',
        '#include "cutscene.h"',
        '#include "cutscene_commands.h"',
        '#include "camera.h"',
        '#include "object.h"',
        '#include "sequence.h"',
        '#include "array_count.h"',
        '',
        'extern u8 _spot04_room_0SegmentRomStart[];',
        'extern u8 _spot04_room_0SegmentRomEnd[];',
        'extern CollisionHeader gPalletCollision;',
        'extern RomFile gPalletRoomList[];',
        'extern ActorEntry gPalletPlayerSpawns[];',
        'extern Spawn gPalletEntrances[];',
        'extern EnvLightSettings gPalletLights[];',
        '',
        'SceneCmd gPalletSceneHeader[] = {',
        '    SCENE_CMD_COL_HEADER(&gPalletCollision),',
        '    SCENE_CMD_ROOM_LIST(1, gPalletRoomList),',
        '    SCENE_CMD_SOUND_SETTINGS(0, 0, NA_BGM_DISABLED),',
        '    SCENE_CMD_MISC_SETTINGS(0, 0),',
        '    SCENE_CMD_SPECIAL_FILES(0, OBJECT_GAMEPLAY_FIELD_KEEP),',
        '    SCENE_CMD_SKYBOX_SETTINGS(1, 0, LIGHT_MODE_TIME),',
        '    SCENE_CMD_ENV_LIGHT_SETTINGS(4, gPalletLights),',
        '    SCENE_CMD_SPAWN_LIST(gPalletEntrances),',
        f'    SCENE_CMD_PLAYER_ENTRY_LIST({len(spawns)}, gPalletPlayerSpawns),',
        '    SCENE_CMD_END(),',
        '};', '',
        'RomFile gPalletRoomList[] = {',
        '    { (uintptr_t)_spot04_room_0SegmentRomStart,',
        '      (uintptr_t)_spot04_room_0SegmentRomEnd },',
        '};',
        'ActorEntry gPalletPlayerSpawns[] = {',
        *[f'    {{ ACTOR_PLAYER, {{ {x}, {y}, {z} }}, {{ 0, DEG_TO_BINANG({yaw}.0f), 0 }}, PLAYER_PARAMS(PLAYER_START_MODE_IDLE, PLAYER_START_BG_CAM_DEFAULT) }},' for x,y,z,yaw in spawns],
        '};',
        'Spawn gPalletEntrances[] = { '+', '.join('{ '+str(i)+', 0 }' for i in range(len(spawns)))+' };',
        '/* Compatibility only: these Zelda cutscenes are still referenced by', 
        ' * compiled but unreachable Zelda code and actor overlays. Never', 
        ' * trigger them in Pallet Town. Minimal valid scripts preserve the', 
        ' * upstream link contract without retaining Kokiri Forest assets. */',
        'CutsceneData gKokiriForestDekuSproutPart3Cs[] = {',
        '    CS_HEADER(0, 1), CS_END_OF_SCRIPT(),',
        '};',
        'CutsceneData gKokiriForestSariaGreetingCs[] = {',
        '    CS_HEADER(0, 1), CS_END_OF_SCRIPT(),',
        '};', '',
        'EnvLightSettings gPalletLights[4] = {',
    ]
    light = [
        ((110,118,110),(73,-73,73),(221,217,199),(-73,73,-73),(56,68,80),(121,150,164),994,12800),
        ((120,126,125),(73,-73,73),(255,249,235),(-73,73,-73),(76,85,102),(128,178,192),997,12800),
        ((127,105,97),(73,-73,73),(241,173,117),(-73,73,-73),(65,56,93),(160,138,126),994,12800),
        ((40,52,70),(73,-73,73),(87,97,127),(-73,73,-73),(45,45,72),(74,84,113),993,12800),
    ]
    for ambient,dir0,color0,dir1,color1,fog,near,far in light:
        lines.append('    { {'+', '.join(map(str,ambient))+'}, {'+', '.join(map(str,dir0))+
                    '}, {'+', '.join(map(str,color0))+'}, {'+', '.join(map(str,dir1))+
                    '}, {'+', '.join(map(str,color1))+'}, {'+', '.join(map(str,fog))+
                    f'}}, ((1 << 10) | {near}), {far} }},')
    lines += [
        '};', '',
        'SurfaceType gPalletSurfaceTypes[1] = {',
        '    { SURFACETYPE0(0,0,0,0,0,0,0,0), SURFACETYPE1(0,0,0,0,0,0,0,0) },',
        '};',
        'BgCamInfo gPalletCameras[1] = { { CAM_SET_NORMAL0, 0, NULL } };',
        f'Vec3s gPalletColVertices[{len(vertices)}] = {{',
    ]
    lines += ['    { '+', '.join(map(str,p))+' },' for p in vertices]
    lines += ['};', f'CollisionPoly gPalletColPolys[{len(polys)}] = {{']
    for ids,normal,dist in polys:
        lines.append('    { 0, COLPOLY_VTX('+str(ids[0])+', COLPOLY_IGNORE_NONE),'+
                     ' COLPOLY_VTX('+str(ids[1])+', COLPOLY_IGNORE_NONE),'+
                     ' COLPOLY_VTX_INDEX('+str(ids[2])+'), { '+
                     ', '.join(map(str,normal))+' }, '+str(dist)+' },')
    lines += [
        '};',
        'CollisionHeader gPalletCollision = {',
        f'    {{ {x1}, -30, {z1} }}, {{ {x2}, 365, {z2} }},',
        '    ARRAY_COUNT(gPalletColVertices), gPalletColVertices,',
        '    ARRAY_COUNT(gPalletColPolys), gPalletColPolys,',
        '    gPalletSurfaceTypes, gPalletCameras, 0, NULL',
        '};', '',
    ]
    source='\n'.join(lines)
    if room_name!="PalletTown":
        # Retain compatibility symbols only in the exterior segment.
        start=source.index('/* Compatibility only')
        end=source.index('EnvLightSettings gPalletLights[4] =',start)
        source=source[:start]+source[end:]
        source=source.replace('SCENE_CMD_SKYBOX_SETTINGS(1, 0, LIGHT_MODE_TIME)',
                              'SCENE_CMD_SKYBOX_SETTINGS(0, 0, LIGHT_MODE_SETTINGS)')
        source=source.replace('NA_BGM_FIELD_LOGIC','NA_BGM_DISABLED')
    return source


def room_source(geom: Geometry) -> str:
    lines = [
        '/* Original Pallet Town world, with OoT-native scene collision. */',
        '#include "ultra64.h"',
        '#include "scene.h"',
        '#include "room.h"',
        '#include "gfx.h"',
        '#include "array_count.h"',
        '',
        'extern RoomShapeNormal gPalletRoomShape;',
        'SceneCmd gPalletRoomHeader[] = {',
        '    SCENE_CMD_ROOM_SHAPE(&gPalletRoomShape),',
        '    SCENE_CMD_ECHO_SETTINGS(0),',
        '    SCENE_CMD_ROOM_BEHAVIOR(0, 0, false, false),',
        '    SCENE_CMD_SKYBOX_DISABLES(false, false),',
        '    SCENE_CMD_TIME_SETTINGS(255, 255, 0),',
        '    SCENE_CMD_END(),',
        '};', '',
    ]
    face_groups = [geom.faces[i:i+10] for i in range(0,len(geom.faces),10)]
    for index, group in enumerate(face_groups):
        lines.append(f'Vtx gPalletVertices{index}[{3*len(group)}] __attribute__((aligned(16))) = {{')
        for pts,col in group:
            for p in pts:
                if any(abs(k)>32760 for k in p):
                    raise ValueError("Pallet mesh position overflows N64 vertex coordinates")
                lines.append('    { .v = { .ob = { '+', '.join(map(str,p))+
                             ' }, .flag = 0, .tc = { 0, 0 }, .cn = { '+
                             ', '.join(map(str,col))+', 255 } } },')
        lines.append('};')
    lines += [
        'Gfx gPalletWorldDl[] = {',
        '    gsDPPipeSync(),',
        '    gsSPClearGeometryMode(G_LIGHTING | G_TEXTURE_GEN | G_TEXTURE_GEN_LINEAR | G_CULL_BACK | G_CULL_FRONT),',
        '    gsSPSetGeometryMode(G_SHADE | G_ZBUFFER),',
        '    gsDPSetCycleType(G_CYC_1CYCLE),',
        '    gsDPSetCombineMode(G_CC_SHADE, G_CC_SHADE),',
        '    gsDPSetRenderMode(G_RM_AA_ZB_OPA_SURF, G_RM_AA_ZB_OPA_SURF2),',
        '    gsSPTexture(0, 0, 0, G_TX_RENDERTILE, G_OFF),',
    ]
    for index, group in enumerate(face_groups):
        lines.append(f'    gsSPVertex(gPalletVertices{index}, {3*len(group)}, 0),')
        for offset in range(0,len(group),2):
            a=offset*3
            if offset+1<len(group):
                lines.append(f'    gsSP2Triangles({a},{a+1},{a+2},0,{a+3},{a+4},{a+5},0),')
            else:
                lines.append(f'    gsSP1Triangle({a},{a+1},{a+2},0),')
    lines += [
        '    gsSPEndDisplayList(),',
        '};',
        'RoomShapeDListsEntry gPalletRoomDLists[1] = {',
        '    { gPalletWorldDl, NULL },',
        '};',
        'RoomShapeNormal gPalletRoomShape = {',
        '    ROOM_SHAPE_TYPE_NORMAL,',
        '    ARRAY_COUNT(gPalletRoomDLists),',
        '    gPalletRoomDLists,',
        '    gPalletRoomDLists + ARRAY_COUNT(gPalletRoomDLists),',
        '};', '',
    ]
    return '\n'.join(lines)


def unused_room_source(index: int) -> str:
    """Preserve OoT DMA room slots 1 and 2 without linking Kokiri textures.

    The new Pallet scene exposes exactly one playable room: room 0. Original
    Zelda spot04 rooms 1 and 2 referenced shared Kokiri scene textures.
    Their ROM DMA slots are still required by the pinned linker and tables,
    so replace their contents with tiny valid empty rooms rather than
    leaving dangling Kokiri texture references or deleting DMA entries.
    """
    if index not in (1, 2):
        raise ValueError("Only the two unused Kokiri room slots are replaceable")
    name = f"gPalletEmptyRoom{index}"
    return "\n".join([
        "/* Empty compatibility room preserving the original spot04 DMA slot. */",
        '#include "ultra64.h"',
        '#include "scene.h"',
        '#include "room.h"',
        "",
        f"RoomShapeNormal {name}Shape = {{",
        "    ROOM_SHAPE_TYPE_NORMAL, 0, NULL, NULL,",
        "};",
        f"SceneCmd {name}Header[] = {{",
        f"    SCENE_CMD_ROOM_SHAPE(&{name}Shape),",
        "    SCENE_CMD_ECHO_SETTINGS(0),",
        "    SCENE_CMD_ROOM_BEHAVIOR(0, 0, false, false),",
        "    SCENE_CMD_END(),",
        "};",
        "",
    ])


def split_segment_header(source: str, name: str) -> tuple[str, str]:
    """Put a scene/room command header in its own leading ROM object.

    GCC may reorder module-level initialized globals in a single .o even when
    the header was declared first in C. OoT's scene/room loader ALWAYS reads
    its commands from offset 0, so the linker spec must include a separate
    header object before the geometry/object data.

    This splits after the complete SceneCmd initializer, retaining original
    includes/extern declarations in both translation units. Source functions
    remain available for inspection and synthetic ROM-free testing.
    """
    marker = f"SceneCmd {name}[] = {{"
    if source.count(marker) != 1:
        raise ValueError(f"Expected one {name} command header")
    start = source.index(marker)
    end = source.index("\n};", start) + len("\n};")
    prefix = source[:start]
    header = prefix + source[start:end] + "\n"
    body = prefix + source[end:].lstrip("\n")
    if f"SceneCmd {name}[]" in body:
        raise ValueError(f"Unexpected duplicate header {name}")
    return header, body


def build_segments(room_name="PalletTown"):
    scene,room,metadata=build(room_name)
    prefix="gPallet" if room_name=="PalletTown" else "g"+room_name
    scene_header,scene_body=split_segment_header(scene,prefix+"SceneHeader")
    room_header,room_body=split_segment_header(room,prefix+"RoomHeader")
    return scene_header,scene_body,room_header,room_body,metadata


def build(room_name="PalletTown"):
    geom=Geometry().make(room_name)
    scene,room=scene_source(geom),room_source(geom)
    if room_name!="PalletTown":
        prefix="g"+room_name
        segment=ROOMS[room_name]["segment"]
        scene=scene.replace('gPallet',prefix).replace('_spot04_room_0','_'+segment+'_room_0')
        room=room.replace('gPallet',prefix)
    return scene,room,{
        "landmarks":[l.name for l in LANDMARKS] if room_name=="PalletTown" else [],
        "spawn":(*point(room_name,*ROOMS[room_name]["spawns"][0][:2]),),
        "dimensions":ROOMS[room_name]["dimensions"],
        "triangles":len(geom.faces),
        "collisionPolygons":len(geom.coll_faces),
        "staticRoomBuffers":math.ceil(len(geom.faces)/10),
        "walkableCells":sum(row.count('.') for row in ROOMS[room_name]["static_walkable_rows"]),
        "reference": "pret/pokered ba9c0568f64ae602fadda577a08c66639f93082a",
    }


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("build/pallet-scene-preview"))
    args=parser.parse_args()
    scene,room,meta=build()
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"poke_pallet_scene.c").write_text(scene)
    (args.output/"poke_pallet_room.c").write_text(room)
    print(meta)
