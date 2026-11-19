#!/usr/bin/env python3
"""Build an original Pallet Town OoT scene and room with native collision.

The experimental total conversion uses the SCENE_KOKIRI_FOREST scene slot as a
temporary staging slot, replacing *its ROM scene/room payloads* with original
Pallet Town geometry. No Kokiri mesh, rooms, NPCs or scene collision are loaded.

All vertices, collision walls, and building facades are authored here in a
deterministic, ROM-free recipe. Link, OoT's player, camera and collision stay.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import chain

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


LANDMARKS = (
    Landmark("Red's house", -405, 150, 174, 158, 210, RED, CREAM),
    Landmark("Rival's house", 405, 150, 174, 158, 210, ROOF_BLUE, CREAM),
    Landmark("Professor Oak's laboratory", 0, -650, 320, 195, 230, LAB_ROOF, WHITE),
)
TREES = (
    (-880, -1110), (-875, -860), (-865, -600), (-872, -280), (-880, 200),
    (-850, 530), (-835, 860), (880, -1040), (870, -820), (865, -520),
    (865, -180), (865, 270), (860, 650), (830, 900),
    (-650, -980), (660, -990), (-670, 530), (650, 540),
)
SPAWN = (0, 0, 690)
WORLD_BOUNDS = (-1100, -1300, 1100, 1150)


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

    def building(self, b: Landmark):
        x,z,hx,hz,h = b.x,b.z,b.half_w,b.half_d,b.height
        self.box(x,z,hx,hz,h,b.wall,collide=True)
        peak = h + (92 if b.name.startswith("Professor") else 78)
        x1,x2 = x-hx-19,x+hx+19
        z1,z2 = z-hz-19,z+hz+19
        self.quad((x1,h,z1),(x1,h,z2),(x,peak,z2),(x,peak,z1),b.roof)
        self.quad((x,peak,z1),(x,peak,z2),(x2,h,z2),(x2,h,z1),b.roof)
        self.tri((x1,h,z2),(x2,h,z2),(x,peak,z2), b.wall)
        self.tri((x2,h,z1),(x1,h,z1),(x,peak,z1), b.wall)
        # Front facing south (+Z): entrances and blue-glass windows.
        door_width = 65 if hx < 200 else 91
        self.quad((x-door_width//2,0,z+hz+4),(x+door_width//2,0,z+hz+4),
                  (x+door_width//2,146,z+hz+4),(x-door_width//2,146,z+hz+4),TRUNK)
        for delta in (-int(hx*0.60), int(hx*0.60)):
            self.quad((x+delta-35,94,z+hz+5),(x+delta+35,94,z+hz+5),
                      (x+delta+35,157,z+hz+5),(x+delta-35,157,z+hz+5),WINDOW)
        # Door remains a non-enterable prototype. House collision includes its facade.
        if b.name.startswith("Professor"):
            self.box(x,z+hz+25,112,13,13,(241,239,224),y0=164)
            self.box(x,z+hz+39,80,5,11,LAB_ROOF,y0=166)

    def make(self):
        x1,z1,x2,z2 = WORLD_BOUNDS
        self.flat(x1,z1,x2,z2,-2,GRASS)
        # A continuous path north to Route 1, crossroads to both houses,
        # and a short walkway into the laboratory.
        self.flat(-116,-1260,116,1030,0,ROAD)
        self.flat(-690,315,690,423,0,ROAD)
        self.flat(-615,309,-270,225,0,ROAD)
        self.flat(270,309,615,225,0,ROAD)
        self.flat(-140,-455,140,-402,0,ROAD_EDGE)
        self.flat(-163,-850,163,-848,0,ROAD_EDGE)
        self.flat(-1080,925,1080,1150,0,SEA)
        # Grass strips near Route 1 and homes, visibly different in 3D.
        for i in range(9):
            z = -1240 + 116*i
            self.flat(-405,z,-250,z+80,0,GRASS_DARK)
            self.flat(250,z,405,z+80,0,GRASS_DARK)
        for b in LANDMARKS: self.building(b)
        for x,z in TREES: self.tree(x,z)
        # Decorative route markers and small fences.
        for x,z in ((-160,-1050),(170,-1050),(-240,625),(248,625)):
            self.box(x,z,39,8,96,WHITE)
            self.box(x,z,43,10,10,RED,y0=96)
        for fence_x1,fence_x2,z in ((-695,-250,465),(250,695,465),(-665,-225,-315),(225,665,-315)):
            for x in range(fence_x1,fence_x2,94):
                self.box(x,z,8,8,85,WHITE)
            self.box((fence_x1+fence_x2)//2,z,abs(fence_x2-fence_x1)//2,7,13,WHITE,y0=49)

        # Reliable flat walkable ground and blocking collision for the edges.
        self.collision_quad((x1,0,z1),(x1,0,z2),(x2,0,z2),(x2,0,z1))
        self.collision_quad((x1,0,z2),(x1,360,z2),(x2,360,z2),(x2,0,z2))
        self.collision_quad((x2,0,z1),(x2,360,z1),(x1,360,z1),(x1,0,z1))
        self.collision_quad((x1,0,z1),(x1,360,z1),(x1,360,z2),(x1,0,z2))
        self.collision_quad((x2,0,z2),(x2,360,z2),(x2,360,z1),(x2,0,z1))
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


def scene_source(geom: Geometry) -> str:
    vertices, polys = _collision_data(geom)
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
        '    SCENE_CMD_SOUND_SETTINGS(0, 0, NA_BGM_FIELD_LOGIC),',
        '    SCENE_CMD_MISC_SETTINGS(0, 0),',
        '    SCENE_CMD_SPECIAL_FILES(0, OBJECT_GAMEPLAY_FIELD_KEEP),',
        '    SCENE_CMD_SKYBOX_SETTINGS(1, 0, LIGHT_MODE_TIME),',
        '    SCENE_CMD_ENV_LIGHT_SETTINGS(4, gPalletLights),',
        '    SCENE_CMD_SPAWN_LIST(gPalletEntrances),',
        '    SCENE_CMD_PLAYER_ENTRY_LIST(1, gPalletPlayerSpawns),',
        '    SCENE_CMD_END(),',
        '};', '',
        'RomFile gPalletRoomList[] = {',
        '    { (uintptr_t)_spot04_room_0SegmentRomStart,',
        '      (uintptr_t)_spot04_room_0SegmentRomEnd },',
        '};',
        f'ActorEntry gPalletPlayerSpawns[] = {{ {{ ACTOR_PLAYER, {{ {SPAWN[0]}, 0, {SPAWN[2]} }},',
        '    { 0, DEG_TO_BINANG(180.0f), 0 }, 0x0FFF } };',
        'Spawn gPalletEntrances[] = { { 0, 0 } };',
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
        '    { -1100, -30, -1300 }, { 1100, 365, 1150 },',
        '    ARRAY_COUNT(gPalletColVertices), gPalletColVertices,',
        '    ARRAY_COUNT(gPalletColPolys), gPalletColPolys,',
        '    gPalletSurfaceTypes, gPalletCameras, 0, NULL',
        '};', '',
    ]
    return '\n'.join(lines)


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


def build_segments():
    """Return header-first OoT objects and original Pallet metadata.

    Link `scene_header` before `scene_body`, and `room_header` before
    `room_body`, in the corresponding spot04 ROM segments. Never combine
    the pairs in a single C object, because GCC can reorder their data.
    """
    scene, room, metadata = build()
    scene_header, scene_body = split_segment_header(scene, "gPalletSceneHeader")
    room_header, room_body = split_segment_header(room, "gPalletRoomHeader")
    return scene_header, scene_body, room_header, room_body, metadata


def build():
    g = Geometry().make()
    scene,room = scene_source(g),room_source(g)
    return scene,room,{
        "landmarks":[l.name for l in LANDMARKS],
        "spawn":SPAWN,
        "triangles":len(g.faces),
        "collisionPolygons":len(g.coll_faces),
        "staticRoomBuffers":math.ceil(len(g.faces)/10),
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
