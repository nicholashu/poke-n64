#!/usr/bin/env python3
"""Compile a user-supplied English Red/Blue Pallet Town into native OoT data.

The extractor reads the ROM. This module supplies original 3D interpretation
rules, not a stored copy of Pallet Town. Generated text and map data are private
build products. No assembly is executed or automatically translated.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
from html import escape
import json
import os
from pathlib import Path
import sys
import tempfile

from pallet_town import (Geometry, CREAM, WHITE, RED, ROOF_BLUE, LAB_ROOF,
                         WINDOW, TRUNK, scene_source, room_source,
                         split_segment_header, _collision_data)

ROOT = Path(__file__).resolve().parents[1]
CELL = 80
FORMAT_VERSION = 1
MAX_MAP_CELLS = 512
# Semantic interpretations of the OVERWORLD tileset's walking-cell samples.
# These IDs are format bindings. Geometry, colours and heights are our own.
BUILDING_TILES = frozenset((0x0F, 0x12, 0x15, 0x17, 0x18, 0x1A, 0x1B,
                            0x22, 0x38, 0x4B, 0x4E, 0x5C))
COLORS = {
    "ground": (206, 202, 158), "grass": (126, 170, 98),
    "meadow": (96, 149, 80), "flowers": (96, 149, 80),
    "tall_grass": (64, 121, 61), "water": (70, 136, 169),
    "boundary": (119, 135, 106), "fence": (216, 211, 177),
    "sign": (153, 110, 71), "building": (215, 202, 169),
    "door": (153, 110, 71),
}
DESTINATIONS = {0x0C: "Route 1", 0x20: "Route 21", 0x25: "Red's house",
                0x27: "Blue's house", 0x28: "Oak's lab"}
TEXT_KEYS = ("oak_hey_wait", "oak_unsafe", "girl", "fisher", "lab_sign",
             "town_sign", "player_house_sign", "rival_house_sign")
ROM_TEXT_KEYS = {1: "oak_unsafe", 2: "girl", 3: "fisher", 4: "lab_sign",
                 5: "town_sign", 6: "player_house_sign", 7: "rival_house_sign"}


def _integer(value, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def point(width: int, height: int, x: int, y: int) -> tuple[int, int, int]:
    """Walking cell centre; GB north is negative N64 Z, ground is N64 Y=0."""
    return ((2 * x + 1 - width) * CELL // 2, 0,
            (2 * y + 1 - height) * CELL // 2)


def classify(cell: dict) -> str:
    tile = cell["collision_tile"]
    if tile == 0x3A:
        return "boundary"
    if tile in (0x14, 0x32):
        return "water"
    if tile == 0x55:
        return "fence"
    if tile == 0x56:
        return "sign"
    if tile == 0x52:
        return "tall_grass"
    if tile == 0x2C:
        return "flowers" if 0x03 in cell["tiles"] else "meadow"
    if tile == 0x39:
        return "grass"
    if tile == 0x23:
        return "ground"
    if tile in BUILDING_TILES:
        return "door" if tile == 0x1B else "building"
    raise ValueError(f"No original 3D rule for OVERWORLD collision tile 0x{tile:02x}")


def validate_world(world: dict) -> dict:
    """Validate the intermediate contract before emitting C or geometry."""
    if not isinstance(world, dict) or world.get("schema_version") != 1:
        raise ValueError("Unsupported Gen 1 extraction schema")
    data = world.get("map")
    if not isinstance(data, dict) or data.get("id") != 0 or data.get("tileset_id") != 0:
        raise ValueError("This compiler supports Pallet Town with OVERWORLD only")
    width = _integer(data.get("width"), 1, 32, "map width")
    height = _integer(data.get("height"), 1, 32, "map height")
    if width * height > MAX_MAP_CELLS:
        raise ValueError("Map exceeds the portable runtime's grid budget")
    cells = data.get("cells")
    if not isinstance(cells, list) or len(cells) != height:
        raise ValueError("Cell rows do not match map height")
    for row in cells:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError("Cell columns do not match map width")
        for cell in row:
            if not isinstance(cell, dict) or type(cell.get("walkable")) is not bool:
                raise ValueError("Every cell needs boolean passability")
            _integer(cell.get("collision_tile"), 0, 255, "collision tile")
            tiles = cell.get("tiles")
            if not isinstance(tiles, list) or len(tiles) != 4:
                raise ValueError("Every walking cell needs four graphics tile IDs")
            for tile in tiles:
                _integer(tile, 0, 255, "graphics tile")
            classify(cell)  # Unsupported semantic tiles never silently become grass.
    for key, limit in (("objects", 16), ("warps", 16), ("signs", 16)):
        records = data.get(key)
        if not isinstance(records, list) or len(records) > limit:
            raise ValueError(f"Invalid {key} list")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"Invalid {key} record")
            _integer(record.get("x"), 0, width - 1, f"{key} x")
            _integer(record.get("y"), 0, height - 1, f"{key} y")
            if key in ("objects", "signs"):
                if record.get("text_id") not in ROM_TEXT_KEYS:
                    raise ValueError("Unsupported Pallet interaction text ID")
            if key == "objects":
                _integer(record.get("id"), 1, 16, "object ID")
                _integer(record.get("sprite_id"), 0, 255, "sprite ID")
                if type(record.get("visible_on_start")) is not bool:
                    raise ValueError("Object visibility must be extracted explicitly")
            if key == "warps":
                _integer(record.get("destination_map"), 0, 255, "destination map")
                _integer(record.get("destination_warp"), 0, 255, "destination warp")
                if not cells[record["y"]][record["x"]]["walkable"]:
                    raise ValueError("Door warp is not on a passable cell")
    ids = [obj["id"] for obj in data["objects"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate object ID")
    oak = [obj for obj in data["objects"] if obj["text_id"] == 1]
    if len(oak) != 1:
        raise ValueError("Known Oak adapter requires exactly one Oak object")
    if not isinstance(data.get("connections"), list) or len(data["connections"]) > 4:
        raise ValueError("Invalid connections list")
    for connection in data["connections"]:
        if connection.get("direction") not in ("north", "south", "west", "east"):
            raise ValueError("Unknown connection direction")
        _integer(connection.get("destination_map"), 0, 255, "connection destination")
    texts = data.get("texts", world.get("texts"))
    if not isinstance(texts, dict):
        raise ValueError("Missing extracted dialogue")
    for name in TEXT_KEYS:
        entry = texts.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            raise ValueError(f"Missing extracted dialogue: {name}")
        if not 0 < len(entry["text"]) < 4096:
            raise ValueError(f"Invalid dialogue length: {name}")
    return data


def _components(kinds: list[list[str]]) -> list[list[tuple[int, int]]]:
    pending = {(x, y) for y, row in enumerate(kinds) for x, kind in enumerate(row)
               if kind in ("building", "door")}
    groups = []
    while pending:
        start = min(pending, key=lambda p: (p[1], p[0]))
        pending.remove(start)
        queue = deque([start])
        group = []
        while queue:
            x, y = queue.popleft()
            group.append((x, y))
            for pos in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if pos in pending:
                    pending.remove(pos)
                    queue.append(pos)
        groups.append(sorted(group, key=lambda p: (p[1], p[0])))
    return groups


def _building(geom: Geometry, cells: list[tuple[int, int]], door: dict,
              width: int, height: int) -> dict:
    xs, ys = zip(*cells)
    x1, x2 = min(xs) * CELL-width*CELL//2, (max(xs)+1)*CELL-width*CELL//2
    z1 = min(ys)*CELL-height*CELL//2
    # The facade runs through the door's cell centre, leaving its front half
    # accessible. Collision comes from the GB passability grid independently.
    z2 = (max(ys)*2+1-height)*CELL//2
    dx, _, dz = point(width, height, door["x"], door["y"])
    is_lab = door["destination_map"] == 0x28
    wall, roof = (WHITE, LAB_ROOF) if is_lab else (
        CREAM, RED if door["destination_map"] == 0x25 else ROOF_BLUE)
    h, peak = (210, 280) if is_lab else (180, 250)
    # Front walls leave a visible doorway. Buildings never add a second,
    # incompatible collision footprint over the source grid.
    for left, right in ((x1, dx-28), (dx+28, x2)):
        if right > left:
            geom.quad((left,0,z2),(right,0,z2),(right,h,z2),(left,h,z2),wall)
    geom.quad((dx-28,125,z2),(dx+28,125,z2),(dx+28,h,z2),(dx-28,h,z2),wall)
    geom.quad((dx-26,0,dz-8),(dx+26,0,dz-8),(dx+26,125,dz-8),(dx-26,125,dz-8),TRUNK)
    for face in (((x2,0,z1),(x1,0,z1),(x1,h,z1),(x2,h,z1)),
                 ((x1,0,z1),(x1,0,z2),(x1,h,z2),(x1,h,z1)),
                 ((x2,0,z2),(x2,0,z1),(x2,h,z1),(x2,h,z2))):
        geom.quad(*face,wall)
    midz = (z1+z2)//2
    geom.quad((x1-8,h,z1-8),(x1-8,peak,midz),(x2+8,peak,midz),(x2+8,h,z1-8),roof)
    geom.quad((x1-8,peak,midz),(x1-8,h,z2+8),(x2+8,h,z2+8),(x2+8,peak,midz),roof)
    geom.tri((x1,h,z1),(x1,peak,midz),(x1,h,z2),wall)
    geom.tri((x2,h,z2),(x2,peak,midz),(x2,h,z1),wall)
    for wx in range(x1+CELL//2, x2, CELL):
        if abs(wx-dx) > CELL//2:
            geom.quad((wx-18,70,z2+2),(wx+18,70,z2+2),
                      (wx+18,119,z2+2),(wx-18,119,z2+2),WINDOW)
    return {"name": DESTINATIONS.get(door["destination_map"], "Building"),
            "cells": [list(p) for p in cells], "door": [door["x"],door["y"]],
            "bounds": [x1,z1,x2,z2], "height": h, "roof_height": peak}


def _spawn(data: dict) -> tuple[int, int]:
    home = next((w for w in data["warps"] if w["destination_map"] == 0x25), None)
    if home is None:
        raise ValueError("Pallet import requires Red's house warp for the outdoor spawn")
    x, y = home["x"], home["y"]+1
    if y >= data["height"] or not data["cells"][y][x]["walkable"]:
        raise ValueError("No passable outdoor spawn directly outside Red's house")
    return x, y


def make_geometry(data: dict) -> tuple[Geometry, dict]:
    width, height = data["width"], data["height"]
    cells = data["cells"]
    kinds = [[classify(cell) for cell in row] for row in cells]
    geom = Geometry()
    minx, minz = -width*CELL//2, -height*CELL//2
    maxx, maxz = width*CELL//2, height*CELL//2
    for y, row in enumerate(kinds):
        for x, kind in enumerate(row):
            cx, _, cz = point(width, height, x, y)
            color = COLORS[kind]
            geom.flat(cx-CELL//2,cz-CELL//2,cx+CELL//2,cz+CELL//2,-2,color)
            if kind == "boundary":
                geom.box(cx,cz,34,34,64,color)
                geom.box(cx,cz,29,29,10,(164,177,142),y0=64)
            elif kind == "fence":
                for offset in (-30,30):
                    geom.box(cx+offset,cz,5,6,66,WHITE)
                geom.box(cx,cz,40,5,12,WHITE,y0=35)
            elif kind == "sign":
                geom.box(cx,cz,5,5,68,TRUNK)
                geom.box(cx,cz,28,6,28,CREAM,y0=49)
            elif kind == "tall_grass":
                for ox,oz in ((-22,-22),(22,-22),(-22,22),(22,22)):
                    geom.tri((cx+ox-8,0,cz+oz),(cx+ox,26,cz+oz),
                             (cx+ox+8,0,cz+oz),(103,156,63))
            elif kind == "flowers":
                geom.flat(cx-10,cz-10,cx+10,cz+10,1,(232,204,152))
    buildings = []
    for component in _components(kinds):
        doors = [warp for warp in data["warps"] if (warp["x"],warp["y"]) in component]
        if len(doors) != 1:
            raise ValueError("Each building component must bind exactly one extracted door warp")
        # A rectangle is a supported authored building rule, not a guessed
        # arbitrary footprint. Reject other arrangements until given a rule.
        xs,ys = zip(*component)
        if len(component) != (max(xs)-min(xs)+1)*(max(ys)-min(ys)+1):
            raise ValueError("Unsupported nonrectangular building footprint")
        buildings.append(_building(geom,component,doors[0],width,height))
    if len(buildings) != len(data["warps"]):
        raise ValueError("A door warp is missing a recognized building footprint")

    geom.collision_quad((minx,0,minz),(minx,0,maxz),(maxx,0,maxz),(maxx,0,minz))
    edges = []
    for y,row in enumerate(cells):
        for x,cell in enumerate(row):
            if not cell["walkable"]:
                continue
            x1,z1=minx+x*CELL,minz+y*CELL
            x2,z2=x1+CELL,z1+CELL
            # Vertices wind so each wall normal points into the passable cell.
            for dx,dy,a,b in ((0,-1,(x2,z1),(x1,z1)),
                              (0,1,(x1,z2),(x2,z2)),
                              (-1,0,(x1,z1),(x1,z2)),
                              (1,0,(x2,z2),(x2,z1))):
                nx,ny=x+dx,y+dy
                if 0 <= nx < width and 0 <= ny < height and cells[ny][nx]["walkable"]:
                    continue
                # All map exits are sealed until destination scenes exist.
                geom.collision_quad((a[0],0,a[1]),(a[0],330,a[1]),
                                    (b[0],330,b[1]),(b[0],0,b[1]))
                edges.append([x,y,dx,dy])
    vertices,polygons=_collision_data(geom)
    if len(geom.faces)>4096 or len(polygons)>4096:
        raise ValueError("Generated Pallet exceeds the initial scene geometry budget")
    sx,sy=_spawn(data)
    info={"format_version":FORMAT_VERSION,"dimensions_cells":[width,height],
          "cell_size":CELL,"bounds":[minx,minz,maxx,maxz],
          "spawn_cell":[sx,sy],"spawn":list(point(width,height,sx,sy)),
          "buildings":buildings,"landmarks":[b["name"] for b in buildings],
          "triangles":len(geom.faces),"collision_polygons":len(polygons),
          "collision_vertices":len(vertices),"blocked_edges":edges,
          "walkable_cells":sum(cell["walkable"] for row in cells for cell in row),
          "semantic_counts":dict(sorted(Counter(k for row in kinds for k in row).items()))}
    return geom,info


def _c_string(value: str) -> str:
    # Ensure ASCII on GfxPrint's limited font, with explicit default name tokens.
    replacements={"<PKMN>":"POKEMON","<PK>":"PO","<MN>":"KEMON","<TARGET>":"TARGET",
                  "<USER>":"USER","‘":"'","’":"'","“":'"',"”":'"',
                  "…":"...","♂":"M","♀":"F","¥":"Y",
                  "<PLAYER>":"RED","<RIVAL>":"BLUE","{PLAYER}":"RED",
                  "{RIVAL}":"BLUE","POKé":"POKE","é":"e","É":"E",
                  "’":"'","…":"..."}
    for source,target in replacements.items():
        value=value.replace(source,target)
    if len(value)>=4096:
        raise ValueError("Rendered dialogue exceeds the native text budget")
    if any(ord(ch)>126 or (ord(ch)<32 and ch not in "\n\f") for ch in value):
        raise ValueError("Dialogue contains a character the native preview font cannot display")
    return json.dumps(value,ensure_ascii=True)


def native_data_source(world: dict, info: dict) -> str:
    """Emit portable immutable data; runtime declarations are the public ABI."""
    data=world["map"]
    texts=data.get("texts",world.get("texts"))
    lines=['/* Generated from a user-supplied ROM. Keep private; do not commit. */',
           '#include "poke_pallet_import.h"','',
           'static const uint8_t sWalkable[] = {']
    lines += ['    '+', '.join('1' if c["walkable"] else '0' for c in row)+','
              for row in data["cells"]]
    lines += ['};','static const PokePalletObject sObjects[] = {']
    for obj in data["objects"]:
        key=ROM_TEXT_KEYS[obj["text_id"]].upper()
        lines.append(f'    {{ {obj["id"]}, {obj["x"]}, {obj["y"]}, {obj["sprite_id"]}, '
                     f'{int(obj["visible_on_start"])}, POKE_PALLET_TEXT_{key} }},')
    lines+=['};','static const PokePalletWarp sWarps[] = {']
    for warp in data["warps"]:
        dest=warp["destination_map"]
        lines.append(f'    {{ {warp["x"]}, {warp["y"]}, {dest}, {warp["destination_warp"]}, '
                     f'{_c_string(DESTINATIONS.get(dest,"Map "+str(dest)))} }},')
    lines+=['};','static const PokePalletSign sSigns[] = {']
    for sign in data["signs"]:
        lines.append(f'    {{ {sign["x"]}, {sign["y"]}, '
                     f'POKE_PALLET_TEXT_{ROM_TEXT_KEYS[sign["text_id"]].upper()} }},')
    if not data["signs"]:
        lines.append('    { 0, 0, POKE_PALLET_TEXT_NONE },')
    lines+=['};','static const PokePalletConnection sConnections[] = {']
    for conn in data["connections"]:
        dest=conn["destination_map"]
        lines.append(f'    {{ POKE_PALLET_{conn["direction"].upper()}, {dest}, '
                     f'{_c_string(DESTINATIONS.get(dest,"Map "+str(dest)))} }},')
    if not data["connections"]:
        lines.append('    { POKE_PALLET_NORTH, 0, "" },')
    oak=next(obj for obj in data["objects"] if obj["text_id"]==1)
    lab_index=next((i for i,w in enumerate(data["warps"]) if w["destination_map"]==0x28),None)
    if lab_index is None:
        raise ValueError("Oak adapter requires an extracted laboratory warp")
    lines+=['};', 'static const char* const sTexts[POKE_PALLET_TEXT_COUNT] = {',
            '    [POKE_PALLET_TEXT_NONE] = "",']
    for key in TEXT_KEYS:
        lines.append(f'    [POKE_PALLET_TEXT_{key.upper()}] = {_c_string(texts[key]["text"])},')
    lines+=['};','', 'const PokePalletMap gPokePalletMap = {',
            '    .enabled = 1,',f'    .width = {data["width"]}, .height = {data["height"]},',
            f'    .spawn_x = {info["spawn_cell"][0]}, .spawn_y = {info["spawn_cell"][1]},',
            f'    .oak_object_id = {oak["id"]}, .lab_warp_index = {lab_index},',
            '    .walkable = sWalkable,',
            f'    .objects = sObjects, .object_count = {len(data["objects"])},',
            f'    .warps = sWarps, .warp_count = {len(data["warps"])},',
            f'    .signs = sSigns, .sign_count = {len(data["signs"])},',
            f'    .connections = sConnections, .connection_count = {len(data["connections"])},',
            '    .texts = sTexts,','};','']
    if world.get("opening_texts") is not None:
        from opening_rom import emit_opening_c
        lines.append(emit_opening_c(world["opening_texts"], _c_string))
    else:
        # Synthetic map fixtures exercise geometry only, not ROM text.
        lines.extend([
            '#include "poke_intro.h"',
            'const unsigned gPokeOpeningTextEnabled = 0;',
            'const char* const gPokeOpeningTalks[TALK_PC_FULL + 1] = { 0 };',
            'const char* const gPokeOpeningStarters[3] = { 0 };',
            'const char* const gPokeOpeningResults[2] = { 0 };',
        ])
    return '\n'.join(lines)


def compile_world(world: dict) -> dict:
    """Compiler entry for the validated extraction IR, including synthetic tests."""
    data=validate_world(world)
    geom,info=make_geometry(data)
    # The Red/Blue map has three house/lab doors. Retain all corresponding
    # OoT spawn indices so the full bedroom -> Oak -> rival opening can return
    # from each interior. Synthetic incomplete fixtures retain preview mode.
    warp_by_map={w["destination_map"]:w for w in data["warps"]}
    opening_ids=(0x25,0x27,0x28)
    opening_spawns=None
    if all(key in warp_by_map for key in opening_ids):
        opening_spawns=[]
        for key in opening_ids:
            door=warp_by_map[key]
            x,z=door["x"],door["y"]+1
            if z>=data["height"] or not data["cells"][z][x]["walkable"]:
                raise ValueError("Extracted Red/Blue interior return spawn is blocked")
            px,py,pz=point(data["width"],data["height"],x,z)
            opening_spawns.append((px,py,pz,0))
    scene=scene_source(
        geom,bounds=tuple(info["bounds"]),
        spawn=None if opening_spawns is not None else tuple(info["spawn"]),
        spawn_list=opening_spawns,
    )
    info["interior_return_spawns"]=len(opening_spawns) if opening_spawns else 0
    scene=scene.replace('NA_BGM_FIELD_LOGIC','NA_BGM_DISABLED')
    room=room_source(geom)
    sh,sb=split_segment_header(scene,'gPalletSceneHeader')
    rh,rb=split_segment_header(room,'gPalletRoomHeader')
    info.update({"source":world["source"],"coverage":{
        "map_blocks":"extracted", "static_collision":"extracted",
        "warps_and_connections":"extracted; connected to existing indoor story where supported",
        "npc_positions_and_visibility":"extracted; background wandering not implemented",
        "dialogue":("all mapped opening speeches extracted from cartridge; "
                    "unsupported interactions remain unavailable"
                    if world.get("opening_texts") else "synthetic fixture without opening dialogue"),
        "oak_event":"authored gen1_pallet_oak_v1 adapter; collision-aware 3D escort",
        "assembly_translation":False,"post_lab_events":False,"sram_persistence":False,
        "music":False,"interior_collision":bool(world.get("rooms")),
        "interior_procedural_art":bool(world.get("rooms")),
        "interior_object_runtime":False,"interiors":False,"yellow":False},
        "verification":"Generated data only. Requires native build and emulator verification."})
    return {"scene_header":sh,"scene":sb,"room_header":rh,"room":rb,
            "data_source":native_data_source(world,info),"metadata":info,"world":world}


def compile_pallet(rom: bytes) -> dict:
    from gen1_rom import extract_pallet
    return compile_world(extract_pallet(rom))


def preview_svg(result: dict) -> str:
    """Exact extracted grid preview, not a render or emulated game screenshot."""
    data,meta=result["world"]["map"],result["metadata"]
    scale=24
    width,height=data["width"]*scale,data["height"]*scale
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height+70}" '
           f'viewBox="0 0 {width} {height+70}">',
           '<rect width="100%" height="100%" fill="#182825"/>',
           '<g transform="translate(0 42)">']
    for y,row in enumerate(data["cells"]):
        for x,cell in enumerate(row):
            kind=classify(cell)
            color='#'+''.join(f'{c:02x}' for c in COLORS[kind])
            label=f'{x},{y} {kind}; '+('walkable' if cell["walkable"] else 'blocked')
            lines.append(f'<rect x="{x*scale}" y="{y*scale}" width="24" height="24" '
                         f'fill="{color}" stroke="#000" stroke-opacity=".15"><title>{label}</title></rect>')
            if not cell["walkable"]:
                lines.append(f'<path d="M{x*scale+8},{y*scale+8}l8,8m-8,0l8,-8" '
                             'stroke="#21302b" stroke-opacity=".45"/>')
    for obj in data["objects"]:
        opacity='1' if obj["visible_on_start"] else '.45'
        lines.append(f'<circle cx="{obj["x"]*scale+12}" cy="{obj["y"]*scale+12}" '
                     f'r="8" fill="#f4dc94" stroke="#172e29" opacity="{opacity}">'
                     f'<title>Object {obj["id"]}; initially '
                     f'{"visible" if obj["visible_on_start"] else "hidden"}</title></circle>')
    for warp in data["warps"]:
        lines.append(f'<rect x="{warp["x"]*scale+5}" y="{warp["y"]*scale+5}" '
                     'width="14" height="14" fill="#b2d9ef" stroke="#172e29">'
                     f'<title>{escape(DESTINATIONS.get(warp["destination_map"],"Warp"))}</title></rect>')
    sx,sy=meta["spawn_cell"]
    lines += [f'<circle cx="{sx*scale+12}" cy="{sy*scale+12}" r="5" fill="#e6584f"/>',
              '</g>', '<g fill="#f4f1dc" font-family="sans-serif" font-size="12">',
              '<text x="8" y="18">Pallet Town: extracted walking grid</text>',
              '<text x="8" y="34">Crosses = blocked; blue = doors; red = spawn</text>',
              f'<text x="8" y="{height+61}">Data preview only, not emulator output.</text>',
              '</g></svg>']
    return '\n'.join(lines)+'\n'


def write_bundle(result: dict, directory: Path) -> dict:
    """Write only after compilation succeeds; atomically replace each output."""
    outputs={"pallet.json":json.dumps(result["world"],indent=2,sort_keys=True)+'\n',
             "report.json":json.dumps(result["metadata"],indent=2,sort_keys=True)+'\n',
             "preview.svg":preview_svg(result),
             "poke_pallet_scene_header.c":result["scene_header"],
             "poke_pallet_scene.c":result["scene"],
             "poke_pallet_room_header.c":result["room_header"],
             "poke_pallet_room.c":result["room"],
             "poke_pallet_data.c":result["data_source"]}
    manifest={"format_version":FORMAT_VERSION,"input":result["world"]["source"],
              "files":{name:hashlib.sha256(text.encode()).hexdigest() for name,text in outputs.items()}}
    outputs["manifest.json"]=json.dumps(manifest,indent=2,sort_keys=True)+'\n'
    directory.mkdir(parents=True,exist_ok=True)
    # Do not let an output symlink redirect a private asset write unexpectedly.
    for name in outputs:
        if (directory/name).is_symlink():
            raise ValueError(f"Refusing to replace a symlink output: {directory/name}")
    for name,text in outputs.items():
        dest=directory/name
        if dest.is_file() and dest.read_bytes()==text.encode():
            continue
        with tempfile.NamedTemporaryFile(dir=directory,prefix='.'+name+'.',delete=False) as temporary:
            temporary.write(text.encode())
            tmp=Path(temporary.name)
        try:
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
    return manifest


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    env_rom=os.environ.get('POKE_POKEMON_ROM')
    parser.add_argument('--rom',type=Path,default=Path(env_rom) if env_rom else None)
    parser.add_argument('--output',type=Path,default=ROOT/'build/gen1/pallet')
    parser.add_argument('--check',action='store_true',help='validate and compile in memory without writing')
    args=parser.parse_args()
    if args.rom is None:
        raise ValueError('Supply --rom /path/to/pokemon-red.gb or POKEMON_ROM for make import-pallet')
    if args.rom.stat().st_size != 1024*1024:
        raise ValueError('Expected an uncompressed 1 MiB English Red or Blue Game Boy ROM')
    result=compile_pallet(args.rom.read_bytes())
    if not args.check:
        write_bundle(result,args.output)
    meta=result['metadata']
    print(f"Validated {meta['source']['game']}; Pallet {meta['dimensions_cells'][0]} x "
          f"{meta['dimensions_cells'][1]} cells, {len(meta['buildings'])} buildings, "
          f"{meta['walkable_cells']} passable cells.")
    print(f"Generated {meta['triangles']} visual triangles and {meta['collision_polygons']} collision polygons.")
    if not args.check:
        print(f"Private generated output: {args.output}")
    print('Outdoor map and Oak adapter only; interiors, later events, and Yellow are not implemented.')
    print('No N64 ROM linked or emulator run by this command.')


if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError) as exc:
        sys.exit(f'Pallet import failed: {exc}')
