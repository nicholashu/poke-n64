"""Semantic Gen 1 opening-area coordinates shared by geometry and native code.

The JSON contains functional layout facts, not Game Boy graphics or ROM data.
Its pinned reference lets tests compare every static passability cell.
"""
from __future__ import annotations
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "assets/maps/pallet_opening.json"
DATA = json.loads(SOURCE.read_text())
ROOMS = DATA["rooms"]
ORDER = ("PalletTown", "RedsHouse2F", "RedsHouse1F", "BluesHouse", "OaksLab")
CELL = DATA["cell_units"]


def bounds(name):
    w, h = ROOMS[name]["dimensions"]
    return (-w*CELL//2, -h*CELL//2, w*CELL//2, h*CELL//2)


def point(name, x, z):
    left, north, _, _ = bounds(name)
    return (round(left+(x+0.5)*CELL), round(north+(z+0.5)*CELL))


def walkable(name, x, z):
    room = ROOMS[name]
    w, h = room["dimensions"]
    return 0 <= x < w and 0 <= z < h and room["static_walkable_rows"][z][x] == "."


def validate():
    for name in ORDER:
        room = ROOMS[name]
        w, h = room["dimensions"]
        for key in ("semantic_rows", "static_walkable_rows"):
            rows = room[key]
            if len(rows) != h or any(len(row) != w for row in rows):
                raise ValueError(f"{name}: malformed {key}")
        for x, z, _ in room["spawns"]:
            if not walkable(name, x, z):
                raise ValueError(f"{name}: blocked spawn {(x,z)}")
        for warp in room["warps"]:
            if not walkable(name, *warp["at"]):
                raise ValueError(f"{name}: blocked warp")
            if not 0 <= warp["spawn"] < len(ROOMS[warp["destination"]]["spawns"]):
                raise ValueError(f"{name}: invalid destination spawn")


def core_source(rooms=None):
    """Generate playable collision and warp tables from the supplied GB ROM.

    For ROM-free developer builds, retain the authored five-room fixture.
    Map IDs and warp destination semantics come from pret/pokered.
    """
    validate()
    if rooms is not None and set(rooms) != set(ORDER):
        raise ValueError("Imported opening must contain every first-area map")
    ids = {0x00:"PalletTown", 0x25:"RedsHouse1F", 0x26:"RedsHouse2F",
           0x27:"BluesHouse", 0x28:"OaksLab"}
    # The ROM encodes *which warp* to use. The native scene indices are
    # different because the door tiles are one or two cells wide.
    entry_spawns = {
        ("PalletTown", "RedsHouse1F"):1,
        ("PalletTown", "BluesHouse"):0,
        ("PalletTown", "OaksLab"):0,
        ("RedsHouse1F", "PalletTown"):0,
        ("RedsHouse1F", "RedsHouse2F"):1,
        ("RedsHouse2F", "RedsHouse1F"):0,
        ("BluesHouse", "PalletTown"):1,
        ("OaksLab", "PalletTown"):2,
    }
    lines = ['/* Generated from a user-supplied ROM when available. */',
             '#include "poke_intro.h"']
    for i,name in enumerate(ORDER):
        if rooms is None:
            rows=ROOMS[name]["static_walkable_rows"]
        else:
            room=rooms[name]
            rows=[''.join('.' if c["walkable"] else '#' for c in row)
                  for row in room["cells"]]
        lines += [f'static const char* const sMap{i}[] = {{']
        lines += [f'    "{row}",' for row in rows]
        lines += ['};']
    lines += ['const PokeIntroMap gPokeIntroMaps[INTRO_ROOM_COUNT] = {']
    for i,name in enumerate(ORDER):
        if rooms is None:
            room=ROOMS[name]; w,h=room["dimensions"]
        else:
            room=rooms[name]; w,h=room["width"],room["height"]
        lines.append(f'    {{ {w}, {h}, "{ROOMS[name]["title"]}", sMap{i} }},')
    lines += ['};', 'const PokeIntroWarp gPokeIntroWarps[] = {']
    for i,name in enumerate(ORDER):
        if rooms is None:
            warps=[(w["at"][0],w["at"][1],w["destination"],w["spawn"])
                   for w in ROOMS[name]["warps"]]
        else:
            warps=[]
            for w in rooms[name]["warps"]:
                destination=("PalletTown" if w["destination_uses_last_map"]
                             else ids.get(w["destination_map"]))
                if destination is None or (name,destination) not in entry_spawns:
                    raise ValueError(f"Unimplemented first-area warp: {name} to {destination}")
                warps.append((w["x"],w["y"],destination,entry_spawns[(name,destination)]))
        for x,z,dest,spawn in warps:
            lines.append(f'    {{ {i}, {x}, {z}, {ORDER.index(dest)}, {spawn} }},')
    lines += ['};',
              'const unsigned gPokeIntroWarpCount = sizeof(gPokeIntroWarps)/sizeof(gPokeIntroWarps[0]);', '']
    if rooms is None:
        lines += [
            'const PokeIntroObject gPokeIntroObjects[1] = {{0}};',
            'const unsigned gPokeIntroObjectCount = 0;',
            'const PokeIntroSign gPokeIntroSigns[1] = {{0}};',
            'const unsigned gPokeIntroSignCount = 0;',
        ]
    else:
        objects = [(i,obj) for i,name in enumerate(ORDER)
                   for obj in rooms[name]["objects"]]
        signs = [(i,sign) for i,name in enumerate(ORDER)
                 for sign in rooms[name]["signs"]]
        lines += ['const PokeIntroObject gPokeIntroObjects[] = {']
        for i,obj in objects:
            lines.append('    { %d, %d, %d, %d, %d, %d, %d },' % (
                i,obj["id"],obj["x"],obj["y"],obj["sprite_id"],
                obj["text_id"],int(obj["visible_on_start"])))
        lines += ['};',
                  f'const unsigned gPokeIntroObjectCount = {len(objects)};',
                  'const PokeIntroSign gPokeIntroSigns[] = {']
        for i,sign in signs:
            lines.append('    { %d, %d, %d, %d },' % (
                i,sign["x"],sign["y"],sign["text_id"]))
        if not signs:
            lines.append('    {0,0,0,0},')
        lines += ['};',f'const unsigned gPokeIntroSignCount = {len(signs)};']
    return '\n'.join(lines)


def native_header():
    lines = ['#ifndef POKE_WORLD_NATIVE_H', '#define POKE_WORLD_NATIVE_H', '#include "scene.h"', '#include "poke_intro.h"',
             f'#define POKE_WORLD_CELL {CELL}',
             'static const s16 sPokeSceneIds[INTRO_ROOM_COUNT] = {']
    lines += [f'    {ROOMS[n]["scene"]},' for n in ORDER]
    lines += ['};', 'static const s16 sPokeEntrances[INTRO_ROOM_COUNT] = {']
    lines += [f'    {ROOMS[n]["entrance"]},' for n in ORDER]
    lines += ['};', '#endif', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(core_source())
